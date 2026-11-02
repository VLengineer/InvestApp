"""Composition Root: сборка графа зависимостей приложения (паттерн DI-контейнера).

Никакой модуль нижнего слоя не импортирует этот файл — зависимости внедряются
снаружи, что делает слои тестируемыми (подмена моками в conftest.py).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.clients.ollama import OllamaEmbeddingClient
from app.core.config import Settings
from app.db.database import Database
from app.repositories.document_repository import DocumentRepository
from app.services.indexing_service import IndexingService
from app.services.kb_reader import KnowledgeBaseReader
from app.workers.task_registry import TaskRegistry
from news_analyzer.repository import NewsRepository
from news_analyzer.service import NewsAnalyzerService

logger = logging.getLogger(__name__)


class _LazyRepository(DocumentRepository):
    """Proxy: репозиторий создаётся до подключения пула и берёт pool у Database в момент вызова."""

    def __init__(self, database: Database, *, model: str) -> None:
        # super().__init__ присваивает self._pool = pool; setter (ниже)
        # перехватывает это назначение и сохраняет ссылку на Database,
        # а getter возвращает живой пул в момент вызова.
        super().__init__(pool=database, model=model)  # type: ignore[arg-type]

    @property  # type: ignore[override]
    def _pool(self):  # noqa: ANN201 - прокси к живому пулу
        return self._stored_pool.pool

    @_pool.setter
    def _pool(self, value) -> None:  # noqa: ANN001
        # без setter'а присваивание в базовом __init__ вызвало бы
        # AttributeError: property '_pool' ... has no setter
        self._stored_pool = value


@dataclass(slots=True)
class Container:
    settings: Settings
    database: Database
    embedder: OllamaEmbeddingClient
    reader: KnowledgeBaseReader
    repository: DocumentRepository
    registry: TaskRegistry
    indexing: IndexingService
    # --- микросервис news_analyzer (код: python_test/news_analyzer/) ---
    news_repository: NewsRepository
    news_analyzer: NewsAnalyzerService
    _closed: bool = field(default=False, repr=False)

    @classmethod
    def build(cls, settings: Settings) -> "Container":
        """Создаёт граф зависимостей; БД-пул подключается в startup()."""
        database = Database(settings)
        embedder = OllamaEmbeddingClient(settings)
        reader = KnowledgeBaseReader(
            settings.kb_root,
            common_dir_names=settings.common_dir_names,
            max_chunk_chars=settings.max_chunk_chars,
        )
        registry = TaskRegistry()
        repository = _LazyRepository(database, model=settings.embedding_model)
        indexing = IndexingService(settings, reader, embedder, repository, registry)
        # Микросервис анализа новостей: репозиторий берёт живой пул у Database
        news_repository = NewsRepository(database)
        news_analyzer = NewsAnalyzerService(news_repository)
        return cls(
            settings, database, embedder, reader, repository, registry, indexing,
            news_repository, news_analyzer,
        )

    async def startup(self) -> None:
        await self.database.connect()
        await self.database.ensure_schema()
        await self.news_repository.ensure_schema()
        logger.info("Схема БД проверена; эмбеддинг-модель: %s", self.settings.embedding_model)
        # Явно проверяем Ollama при старте и пишем результат в лог контейнера —
        # чтобы «ollama не вызывается / модель не загружена» было видно сразу,
        # а не только после первого POST /index.
        ollama = await self.embedder.health()
        if ollama["status"] == "ok":
            logger.info("Ollama: проверка при старте — OK (%s)", ollama["detail"])
        elif ollama["status"] == "degraded":
            logger.warning("Ollama: проверка при старте — %s", ollama["detail"])
        else:
            logger.error("Ollama: проверка при старте — НЕДОСТУПНА (%s)", ollama["detail"])

    async def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.registry.shutdown()
        await self.embedder.aclose()
        await self.database.close()
