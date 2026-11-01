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
        logger.info(
            "План индексации: концептов собрано=%d из файлов=%d", len(concepts), len(sources),
        )

        # нормализуем пути: срезаем «/app/knowledge_base/», ведущий «./» и «knowledge_base/»,
        # сводим разделители к «/» — иначе Swagger-заглушка "string" или абсолютный путь
        # из Dockerfile молча фильтруют ВСЁ и план становится пустым
        def _norm(path: str) -> str:
            p = str(path).strip().replace("\\", "/").lstrip("./")
            for prefix in ("/app/knowledge_base/", "app/knowledge_base/", "knowledge_base/"):
                if p.startswith(prefix):
                    p = p[len(prefix):]
            return p

        wanted_paths = {_norm(p) for p in (options.get("source_paths") or []) if str(p).strip()}
        if wanted_paths:
            available = sorted({c.source_path for c in concepts})
            before = len(concepts)
            concepts = [c for c in concepts if _norm(c.source_path) in wanted_paths]
            logger.info(
                "План индексации: фильтр source_paths=%s — концептов %d -> %d",
                sorted(wanted_paths), before, len(concepts),
            )
            if not concepts and before:
                logger.warning(
                    "План индексации: source_paths не совпали ни с одним файлом KnowledgeBaseReader; "
                    "доступные пути (первые 10 из %d): %s",
                    len(available), ", ".join(available[:10]),
                )

        # дедупликация внутри запуска (один hash может встречаться в разных файлах)
        unique: dict[str, Concept] = {}
        for concept in concepts:
            unique.setdefault(concept.hash, concept)
        plan = list(unique.values())

        existing = await self._repository.existing_hashes()
        embedded = await self._repository.embedded_document_ids()
        force = bool(options.get("force_reindex"))
        logger.info(
            "План индексации: в kb_documents уже есть hash'ей=%d, эмбеддингов (model=%s)=%d, force_reindex=%s",
            len(existing), self._settings.embedding_model, len(embedded), force,
        )

        to_embed: list[Concept] = []
        already_ok = 0
        for concept in plan:
            doc_id = existing.get(concept.hash)
            if doc_id is not None and doc_id in embedded and not force:
                already_ok += 1
                continue
            to_embed.append(concept)

        # ВАЖНО: limit применяется ПОСЛЕ подсчёта summary, чтобы в ответе API и в логах
        # было видно и «полный план» (сколько осталось без лимита), и сам лимит.
        # Иначе GET /index с limit_documents=1 выглядит как «заиндексирован только 1 документ».
        limit = options.get("limit_documents")
        full_remaining = len(to_embed)
        if limit:
            to_embed = to_embed[: int(limit)]
            logger.info(
                "План индексации: применён limit_documents=%d — концептов к обработке %d -> %d "
                "(это ОТЛАДОЧНЫЙ лимит: полный план был %d, для полной индексации запустите POST /index "
                "БЕЗ limit_documents)",
                limit, full_remaining, len(to_embed), full_remaining,
            )

        summary = {
            "files_found": len(sources),
            "files_with_errors": [s.rel_path for s in sources if s.error],
            "concepts_total": len(concepts),
            "unique_concepts": len(plan),
            "already_indexed": already_ok,
            "to_embed": len(to_embed),
            "to_embed_full": full_remaining,  # сколько осталось бы без limit_documents
            "limit_documents": int(limit) if limit else None,
        }
        return to_embed, summary

    # --------------------------------- запуск --------------------------------
    async def start(self, options: dict[str, Any], requested_by: str) -> tuple[IndexTask, dict[str, Any]]:
        logger.info("Индексация: запрошен запуск (requested_by=%s, options=%s)", requested_by, options)
        try:
            task = await self._registry.create(options, requested_by)
        except TaskAlreadyRunningError as exc:
            logger.warning("Индексация отклонена: %s", exc)
            raise TaskConflictError(str(exc)) from exc
        logger.info("Индексация: создана фоновая задача %s, строится план…", task.task_id)
        plan, summary = await self.build_plan(options)
        task.total = len(plan)
        task.options = {**options, "plan_summary": summary}
        logger.info(
            "Индексация %s: план готов — файлов=%d, концептов=%d, уникальных=%d, "
            "уже проиндексировано=%d, к обработке=%d",
            task.task_id, summary["files_found"], summary["concepts_total"],
            summary["unique_concepts"], summary["already_indexed"], summary["to_embed"],
        )
        if summary["files_with_errors"]:
            logger.warning(
                "Индексация %s: файлы с ошибками (пропущены): %s",
                task.task_id, ", ".join(summary["files_with_errors"]),
            )

        if options.get("dry_run"):
            logger.info("Индексация %s: dry_run=True — в БД/Ollama ничего не отправляется", task.task_id)
            task.status = TaskStatus.SUCCEEDED
            task.finished_at = datetime.now(timezone.utc)
            self._registry.release(task.task_id)
            return task, summary

        if not plan:
            logger.warning(
                "Индексация %s: план пуст — фоновая задача НЕ запускается, в БД ничего не будет. "
                "Причины: (а) все концепты уже проиндексированы (уже проиндексировано=%d), "
                "(б) source_paths отфильтровали всё (см. WARNING выше), (в) limit_documents=0, "
                "(г) файлы не читаются/не содержат объектов id+title (файлы с ошибками=%d).",
                task.task_id, summary["already_indexed"], len(summary["files_with_errors"]),
            )
            task.status = TaskStatus.SUCCEEDED
            task.started_at = datetime.now(timezone.utc)
            task.finished_at = datetime.now(timezone.utc)
            self._registry.release(task.task_id)
            return task, summary

        task._asyncio_task = asyncio.create_task(
            self._run(task, plan), name=f"index-task-{task.task_id}"
        )
        task._asyncio_task.add_done_callback(lambda _t, tid=task.task_id: self._registry.release(tid))
        logger.info("Индексация %s: фоновая задача поставлена в очередь (worker запущен)", task.task_id)
        return task, summary

    # ------------------------------ исполнитель ------------------------------
    async def _run(self, task: IndexTask, plan: list[Concept]) -> None:
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc)
        logger.info(
            "[ЗАДАЧА %s] старт фоновой индексации: концептов к обработке=%d", task.task_id, len(plan),
        )
        consecutive_failures = 0
        try:
            # «по очереди»: последовательно, но с внутренним лимитом через semaphore клиента
            for idx, concept in enumerate(plan, start=1):
                if task.status is TaskStatus.CANCELLED:
                    break
                ok = await self._process_one(task, concept, idx=idx)
                task.processed += 1
                consecutive_failures = 0 if ok else consecutive_failures + 1
                if task.processed % 25 == 0 or not ok:
                    logger.info(
                        "[ЗАДАЧА %s] прогресс %d/%d — новых документов: %d, дублей пропущено: %d, "
                        "ошибок: %d",
                        task.task_id, task.processed, task.total,
                        task.stored_documents, task.skipped_duplicates, task.failed,
                    )
                # защитный стоп: если Ollama/БД систематически недоступны,
                # не «сжигаем» часы на заведомо падающих попытках
                if consecutive_failures >= 10:
                    raise RuntimeError(
                        f"Прервано: {consecutive_failures} подряд неуспешных концептов "
                        f"(последняя ошибка см. в списке errors задачи). "
                        "Проверьте доступность Ollama и PostgreSQL."
                    )
            task.status = TaskStatus.FAILED if task.failed and task.stored_documents == 0 else TaskStatus.SUCCEEDED
        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            logger.warning("[ЗАДАЧА %s] отменена", task.task_id)
            raise
        except Exception as exc:  # noqa: BLE001 - фиксируем, но не роняем сервис
            task.status = TaskStatus.FAILED
            task.add_error("pipeline", exc)
            logger.exception("[ЗАДАЧА %s] завершилась с ошибкой: %s", task.task_id, exc)
        finally:
            task.finished_at = datetime.now(timezone.utc)
            logger.info(
                "[ЗАДАЧА %s] финиш: status=%s обработано=%d/%d новых=%d дублей=%d ошибок=%d; "
                "проверка БД: GET /stats",
                task.task_id, task.status.value, task.processed, task.total,
                task.stored_documents, task.skipped_duplicates, task.failed,
            )
            if task.errors:
                logger.error(
                    "[ЗАДАЧА %s] первые ошибки: %s",
                    task.task_id,
                    "; ".join(f"{e['where']}: {e['error']}" for e in task.errors[:3]),
                )

    async def _process_one(self, task: IndexTask, concept: Concept, *, idx: int) -> bool:
        logger.info(
            "[%d/%d] концепт '%s' (%s, hash=%s, текст %d симв.) — вызов Ollama /api/embeddings…",
            idx, task.total, concept.concept_id, concept.source_path, concept.short_hash,
            len(concept.text),
        )
        try:
            vector = await self._embedder.embed(concept.text)
            task.embedded += 1
            logger.info("[%d/%d] Ollama ответила: эмбеддинг размерности %d получен", idx, task.total, len(vector))
        except Exception as exc:  # noqa: BLE001
            task.add_error(f"embedding:{concept.concept_id}", exc)
            logger.error(
                "[%d/%d] ОШИБКА эмбеддинга '%s': %s: %s",
                idx, task.total, concept.concept_id, exc.__class__.__name__, exc,
            )
            return False
        try:
            logger.info("[%d/%d] запись в БД (kb_documents + kb_embeddings)…", idx, task.total)
            document_id, created_new = await self._repository.save_with_embedding(concept, vector)
            if created_new:
                task.stored_documents += 1
                logger.info("[%d/%d] ДОБАВЛЕН документ document_id=%s", idx, task.total, document_id)
            else:
                task.skipped_duplicates += 1
                logger.info(
                    "[%d/%d] документ с таким content_hash уже был — обновлён существующий document_id=%s",
                    idx, task.total, document_id,
                )
            return True
        except Exception as exc:  # noqa: BLE001
            task.add_error(f"store:{concept.concept_id}", exc)
            logger.error(
                "[%d/%d] ОШИБКА записи в БД '%s': %s: %s",
                idx, task.total, concept.concept_id, exc.__class__.__name__, exc,
            )
            return False
