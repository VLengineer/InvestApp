"""Сервис индексации (Application Service): оркестрация KB -> Ollama -> PostgreSQL.

Конвейер:
  1) KnowledgeBaseReader собирает «общие» JSON и концепты;
  2) дедупликация по content_hash (пропускаем уже проиндексированное);
  3) каждый концепт по очереди прогоняется через эмбеддинг-модель nomic-embed-text;
  4) DocumentRepository пишет документ (uuid) и рядом вектор в kb_embeddings.

Паттерны: Dependency Injection (зависимости приходят в конструктор), Facade над
клиентом/репозиторием, Producer-consumer с ограничением конкурентности.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.clients.ollama import OllamaEmbeddingClient
from app.core.exceptions import TaskConflictError
from app.core.config import Settings
from app.repositories.document_repository import DocumentRepository
from app.services.kb_reader import KnowledgeBaseReader
from app.services.domain import Concept
from app.schemas.api_schemas import TaskStatus
from app.workers.task_registry import IndexTask, TaskAlreadyRunningError, TaskRegistry

logger = logging.getLogger(__name__)


class IndexingService:
    def __init__(
        self,
        settings: Settings,
        reader: KnowledgeBaseReader,
        embedder: OllamaEmbeddingClient,
        repository: DocumentRepository,
        registry: TaskRegistry,
    ) -> None:
        self._settings = settings
        self._reader = reader
        self._embedder = embedder
        self._repository = repository
        self._registry = registry

    # ------------------------------- планирование ---------------------------
    async def build_plan(self, options: dict[str, Any]) -> tuple[list[Concept], dict[str, Any]]:
        concepts, sources = await self._reader.flatten_concepts()

        wanted_paths = set(options.get("source_paths") or [])
        if wanted_paths:
            concepts = [c for c in concepts if c.source_path in wanted_paths]

        # дедупликация внутри запуска (один hash может встречаться в разных файлах)
        unique: dict[str, Concept] = {}
        for concept in concepts:
            unique.setdefault(concept.hash, concept)
        plan = list(unique.values())

        existing = await self._repository.existing_hashes()
        embedded = await self._repository.embedded_document_ids()
        force = bool(options.get("force_reindex"))

        to_embed: list[Concept] = []
        already_ok = 0
        for concept in plan:
            doc_id = existing.get(concept.hash)
            if doc_id is not None and doc_id in embedded and not force:
                already_ok += 1
                continue
            to_embed.append(concept)

        limit = options.get("limit_documents")
        if limit:
            to_embed = to_embed[: int(limit)]

        summary = {
            "files_found": len(sources),
            "files_with_errors": [s.rel_path for s in sources if s.error],
            "concepts_total": len(concepts),
            "unique_concepts": len(plan),
            "already_indexed": already_ok,
            "to_embed": len(to_embed),
        }
        return to_embed, summary

    # --------------------------------- запуск --------------------------------
    async def start(self, options: dict[str, Any], requested_by: str) -> tuple[IndexTask, dict[str, Any]]:
        try:
            task = await self._registry.create(options, requested_by)
        except TaskAlreadyRunningError as exc:
            raise TaskConflictError(str(exc)) from exc
        plan, summary = await self.build_plan(options)
        task.total = len(plan)
        task.options = {**options, "plan_summary": summary}

        if options.get("dry_run"):
            task.status = TaskStatus.SUCCEEDED
            task.finished_at = datetime.now(timezone.utc)
            self._registry.release(task.task_id)
            return task, summary

        task._asyncio_task = asyncio.create_task(
            self._run(task, plan), name=f"index-task-{task.task_id}"
        )
        task._asyncio_task.add_done_callback(lambda _t, tid=task.task_id: self._registry.release(tid))
        return task, summary

    # ------------------------------ исполнитель ------------------------------
    async def _run(self, task: IndexTask, plan: list[Concept]) -> None:
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc)
        logger.info("Задача %s: старт индексации, концептов к обработке: %d", task.task_id, len(plan))
        try:
            # «по очереди»: последовательно, но с внутренним лимитом через semaphore клиента
            for concept in plan:
                if task.status is TaskStatus.CANCELLED:
                    break
                await self._process_one(task, concept)
                task.processed += 1
                if task.processed % 25 == 0:
                    logger.info(
                        "Задача %s: прогресс %d/%d (встроено %d, ошибок %d)",
                        task.task_id, task.processed, task.total, task.stored_documents, task.failed,
                    )
            task.status = TaskStatus.FAILED if task.failed and task.stored_documents == 0 else TaskStatus.SUCCEEDED
        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            logger.warning("Задача %s отменена", task.task_id)
            raise
        except Exception as exc:  # noqa: BLE001 - фиксируем, но не роняем сервис
            task.status = TaskStatus.FAILED
            task.add_error("pipeline", exc)
            logger.exception("Задача %s завершилась с ошибкой", task.task_id)
        finally:
            task.finished_at = datetime.now(timezone.utc)
            logger.info(
                "Задача %s: финиш status=%s stored=%d skipped=%d failed=%d",
                task.task_id, task.status.value, task.stored_documents, task.skipped_duplicates, task.failed,
            )

    async def _process_one(self, task: IndexTask, concept: Concept) -> None:
        try:
            vector = await self._embedder.embed(concept.text)
            task.embedded += 1
        except Exception as exc:  # noqa: BLE001
            task.add_error(f"embedding:{concept.concept_id}", exc)
            return
        try:
            document_id, created_new = await self._repository.save_with_embedding(concept, vector)
            if created_new:
                task.stored_documents += 1
            else:
                task.skipped_duplicates += 1
            logger.debug("Индексировано %s (%s) -> %s", concept.concept_id, concept.short_hash, document_id)
        except Exception as exc:  # noqa: BLE001
            task.add_error(f"store:{concept.concept_id}", exc)
