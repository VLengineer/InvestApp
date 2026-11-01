"""Оркестратор индексации: knowledge_base/*.json -> Ollama embeddings -> pgvector.

Поток:
  1) loader.load_concepts()  — собрать все документы из папки и подпапок;
  2) storage.upsert_documents() — таблица kb_documents (документ + uuid);
  3) embedder.embed_batched()  — эмбеддинги через ollama (embeddinggemma-2);
  4) storage.save_embeddings() — таблица kb_embeddings (вектор + uuid документа).

Чанки не используются: документы уже структурированы, один концепт = один вектор
(chunk_index всегда 0).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.config import Settings
from app.services.embedder import EmbeddingError, OllamaEmbedder
from app.services.loader import Concept, load_concepts
from app.services.storage import RagStorage, _vec_literal

log = logging.getLogger("rag_indexer.indexer")


@dataclass
class IndexProgress:
    state: str = "idle"            # idle | loading | embedding | writing | done | error | cancelled
    total: int = 0
    processed: int = 0
    new_documents: int = 0
    new_embeddings: int = 0
    skipped_duplicates: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)
    started_at: float | None = None
    finished_at: float | None = None
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.started_at:
            d["elapsed_sec"] = round((self.finished_at or time.time()) - self.started_at, 1)
        return d


class Indexer:
    """Управляет индексацией (одна задача за раз) и публикует прогресс."""

    def __init__(self, settings: Settings, storage: RagStorage) -> None:
        self.settings = settings
        self.storage = storage
        self.progress = IndexProgress()
        self._task: asyncio.Task | None = None
        self._cancel = asyncio.Event()

    # ---------- публичный API ----------

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, full_refresh: bool = False) -> IndexProgress:
        """Запускает индексацию в фоне (одна одновременная задача)."""
        if self.busy:
            raise RuntimeError("Индексация уже выполняется")
        self._cancel.clear()
        self.progress = IndexProgress(state="loading", started_at=time.time())
        self._task = asyncio.create_task(self._run(full_refresh))
        return self.progress

    async def cancel(self) -> None:
        if self.busy:
            self._cancel.set()

    async def wait(self, timeout: float | None = None) -> IndexProgress:
        if self._task is None:
            return self.progress
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout)
        except asyncio.TimeoutError:
            pass
        except Exception:  # ошибка уже зафиксирована в progress
            pass
        return self.progress

    # ---------- внутренняя логика ----------

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise asyncio.CancelledError()

    async def _run(self, full_refresh: bool) -> None:
        p = self.progress
        embedder = OllamaEmbedder(
            base_url=self.settings.ollama_base_url,
            model=self.settings.ollama_embed_model,
            timeout=self.settings.embed_request_timeout,
            max_retries=self.settings.embed_max_retries,
            expected_dim=self.settings.embedding_dim,
            concurrency=self.settings.index_concurrency,
        )
        try:
            kb_dir = Path(self.settings.knowledge_base_dir)
            if not kb_dir.is_dir():
                raise FileNotFoundError(f"Каталог базы знаний не найден: {kb_dir}")

            # 1) загрузка JSON (в thread pool — чтобы не блокировать event loop на тысячах файлов)
            report = await asyncio.to_thread(load_concepts, kb_dir, self.settings.max_json_file_size_mb)
            p.errors.extend(report.errors)
            concepts = report.concepts
            p.total = len(concepts)
            if not concepts:
                raise RuntimeError("В knowledge_base не найдено ни одного корректного JSON-документа")
            log.info("Найдено %d документов в %d файлах", len(concepts), report.files_ok)

            # подготовка схемы и проверка размерности эмбеддинга
            await self.storage.ensure_schema(self.settings.embedding_dim)
            dim = await self.storage.check_embedding_dim(self.settings.embedding_dim)
            log.info("Размерность колонки embedding: %s (ожидается %s)", dim, self.settings.embedding_dim)

            if full_refresh:
                log.warning("full_refresh=True: очищаю kb_documents и kb_embeddings")
                await self.storage.truncate_all()

            # 2) документы в первую таблицу
            ids_by_hash = await self.storage.upsert_documents(concepts)
            p.new_documents = sum(1 for c in concepts if c.content_hash in ids_by_hash)
            p.skipped_duplicates = len(concepts) - p.new_documents
            log.info("Документов новых: %d, дубликатов: %d", p.new_documents, p.skipped_duplicates)

            # 3) эмбеддинги батчами + 4) запись во вторую таблицу (пишем по мере получения)
            p.state = "embedding"
            pending = [c for c in concepts if c.text.strip()]
            empty = len(concepts) - len(pending)
            if empty:
                p.errors.append({"file": "-", "error": f"{empty} документов с пустым текстом пропущены"})
            batch_size = max(1, self.settings.embed_batch_size)
            write_queue: asyncio.Queue[tuple[list[Concept], list[list[float]]] | None] = asyncio.Queue(maxsize=4)

            async def writer() -> None:
                while True:
                    item = await write_queue.get()
                    if item is None:  # sentinel — завершить писателя
                        write_queue.task_done()
                        return
                    try:
                        batch_concepts, vectors = item
                        rows = [
                            (ids_by_hash[c.content_hash], _vec_literal(vec), 0)
                            for c, vec in zip(batch_concepts, vectors)
                            if c.content_hash in ids_by_hash
                        ]
                        p.state = "writing"
                        p.new_embeddings += await self.storage.save_embeddings(
                            rows, model=self.settings.ollama_embed_model
                        )
                        p.state = "embedding"
                    finally:
                        write_queue.task_done()

            writer_task = asyncio.create_task(writer())
            try:
                for i in range(0, len(pending), batch_size):
                    self._check_cancel()
                    batch = pending[i : i + batch_size]
                    try:
                        vectors = await embedder.embed([c.text for c in batch])
                    except EmbeddingError as exc:
                        log.error("Батч %d-%d: %s", i, i + len(batch), exc)
                        p.errors.append({
                            "file": ",".join(sorted({c.source_path for c in batch}))[:300],
                            "error": str(exc),
                        })
                        p.processed += len(batch)
                        continue
                    await write_queue.put((batch, vectors))
                    p.processed += len(batch)
                    if i == 0 or (i // batch_size) % 10 == 0:
                        log.info("Эмбеддинги: %d/%d", p.processed, len(pending))
                await write_queue.join()
            finally:
                await write_queue.put(None)  # type: ignore[arg-type]
                await writer_task

            p.state = "cancelled" if self._cancel.is_set() else "done"
            p.message = (
                f"документов новых: {p.new_documents}, эмбеддингов новых: {p.new_embeddings}, "
                f"дубликатов: {p.skipped_duplicates}, ошибок: {len(p.errors)}"
            )
            log.info("Индексация завершена: %s", p.message)
        except asyncio.CancelledError:
            p.state = "cancelled"
            p.message = "Индексация остановлена по запросу"
            log.warning(p.message)
        except Exception as exc:  # noqa: BLE001
            p.state = "error"
            p.message = f"{type(exc).__name__}: {exc}"
            log.exception("Индексация завершилась ошибкой")
        finally:
            await embedder.aclose()
            p.finished_at = time.time()
