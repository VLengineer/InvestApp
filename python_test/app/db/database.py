"""Пул asyncpg + инициализация схемы (идемпотентная, зеркалит init_db/01_init_rag.sql).

Таблицы в проде создаёт docker-entrypoint-initdb.d; здесь та же DDL нужна для
локального запуска/тестов против обычной PostgreSQL. Всё IF NOT EXISTS.
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

from app.core.config import Settings
from app.core.exceptions import ConfigError, DatabaseError

logger = logging.getLogger(__name__)

SCHEMA_DDL: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    "CREATE EXTENSION IF NOT EXISTS pgcrypto",
    """
    CREATE TABLE IF NOT EXISTS kb_documents (
        document_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        source_path   text        NOT NULL,
        concept_id    text        NOT NULL,
        title         text,
        category      text,
        payload       jsonb       NOT NULL,
        content_hash  char(64)    NOT NULL,
        indexed_at    timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_documents_content_hash ON kb_documents (content_hash)",
    "CREATE INDEX IF NOT EXISTS ix_kb_documents_concept_id ON kb_documents (concept_id)",
    "CREATE INDEX IF NOT EXISTS ix_kb_documents_source_path ON kb_documents (source_path)",
    """
    CREATE TABLE IF NOT EXISTS kb_embeddings (
        embedding_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        document_id   uuid NOT NULL REFERENCES kb_documents (document_id) ON DELETE CASCADE,
        chunk_index   int  NOT NULL DEFAULT 0,
        model         text NOT NULL,
        embedding     vector(768) NOT NULL,
        created_at    timestamptz NOT NULL DEFAULT now(),
        UNIQUE (document_id, chunk_index, model)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_kb_embeddings_document_id ON kb_embeddings (document_id)",
)


class Database:
    """Тонкая обёртка над пулом соединений (паттерн Unit of Work даёт транзакции)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is not None:
            return
        try:
            self._pool = await asyncpg.create_pool(
                dsn=self._settings.dsn,
                min_size=self._settings.db_pool_min_size,
                max_size=self._settings.db_pool_max_size,
                server_settings={"application_name": self._settings.app_name},
            )
        except OSError as exc:  # DNS/Connection refused — понятная ошибка конфигурации
            raise ConfigError(f"Не удалось подключиться к PostgreSQL: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise DatabaseError(f"Ошибка инициализации пула БД: {exc.__class__.__name__}") from exc

        async with self._pool.acquire() as conn:
            await conn.execute(f"SET statement_timeout = {int(self._settings.db_statement_timeout_ms)}")
        logger.info("Пул соединений с PostgreSQL создан (max_size=%d)", self._settings.db_pool_max_size)

    async def ensure_schema(self) -> None:
        assert self._pool is not None, "Database.connect() не вызван"
        for ddl in SCHEMA_DDL:
            await self._pool.execute(ddl)
        dim = await self._check_vector_dim()
        if dim and dim != self._settings.embedding_dim:
            raise ConfigError(
                f"В таблице kb_embeddings ожидается vector({self._settings.embedding_dim}), "
                f"а в схеме — vector({dim})"
            )

    async def _check_vector_dim(self) -> int | None:
        row = await self._pool.fetchrow(  # type: ignore[union-attr]
            """
            SELECT a.atttypmod AS typmod
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            WHERE c.relname = 'kb_embeddings' AND a.attname = 'embedding'
            """
        )
        if row is None or row["typmod"] is None or row["typmod"] < 0:
            return None
        return int(row["typmod"])

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise DatabaseError("Пул соединений не инициализирован")
        return self._pool

    def transaction(self) -> Any:
        """Возвращает контекст транзакции (подключается к свободному соединению пула)."""
        return self.pool.acquire()

    async def health(self) -> dict[str, str]:
        try:
            row = await self.pool.fetchrow("SELECT 1 AS ok, (SELECT count(*) FROM kb_documents) AS docs")
            return {"status": "ok", "detail": f"documents={row['docs']}"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "down", "detail": exc.__class__.__name__}

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("Пул соединений закрыт")
