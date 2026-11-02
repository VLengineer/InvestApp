"""Пул asyncpg + инициализация схемы (идемпотентная, зеркалит init_db/01_init_rag.sql).

Таблицы в проде создаёт docker-entrypoint-initdb.d; здесь та же DDL нужна для
локального запуска/тестов против обычной PostgreSQL. Всё IF NOT EXISTS.
"""

from __future__ import annotations

import logging
import time
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

    @staticmethod
    def _dsn_masked(dsn: str) -> str:
        """Показываем хост/порт/БД без пароля (пароль секрет)."""
        from urllib.parse import urlsplit, urlunsplit

        try:
            parts = urlsplit(dsn)
            host = parts.hostname or "?"
            netloc = f"***:***@{host}:{parts.port}" if parts.password else f"{host}:{parts.port}"
            return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
        except Exception:  # noqa: BLE001
            return "<dsn скрыт>"

    async def connect(self) -> None:
        if self._pool is not None:
            return
        target = self._dsn_masked(self._settings.dsn)
        logger.info(
            "PostgreSQL >>> подключение: host=%s port=%s db=%s user=%s pool=%d..%d",
            self._settings.postgres_host, self._settings.postgres_port,
            self._settings.postgres_db, self._settings.postgres_user,
            self._settings.db_pool_min_size, self._settings.db_pool_max_size,
        )
        started = time.perf_counter()
        try:
            self._pool = await asyncpg.create_pool(
                dsn=self._settings.dsn,
                min_size=self._settings.db_pool_min_size,
                max_size=self._settings.db_pool_max_size,
                server_settings={"application_name": self._settings.app_name},
            )
        except OSError as exc:  # DNS/Connection refused — понятная ошибка конфигурации
            logger.error(
                "PostgreSQL <<< ОШИБКА подключения к %s за %.2fs (%s): %s",
                target, time.perf_counter() - started, exc.__class__.__name__, exc,
            )
            raise ConfigError(f"Не удалось подключиться к PostgreSQL ({target}): {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "PostgreSQL <<< ОШИБКА инициализации пула %s за %.2fs (%s): %s",
                target, time.perf_counter() - started, exc.__class__.__name__, exc,
            )
            raise DatabaseError(f"Ошибка инициализации пула БД ({target}): {exc.__class__.__name__}") from exc

        async with self._pool.acquire() as conn:
            await conn.execute(f"SET statement_timeout = {int(self._settings.db_statement_timeout_ms)}")
        logger.info(
            "PostgreSQL <<< OK за %.2fs: пул соединений создан к %s (max_size=%d)",
            time.perf_counter() - started, target, self._settings.db_pool_max_size,
        )

    async def ensure_schema(self) -> None:
        assert self._pool is not None, "Database.connect() не вызван"
        logger.info("PostgreSQL >>> проверка схемы БД (%d DDL-команд, все IF NOT EXISTS)…", len(SCHEMA_DDL))
        started = time.perf_counter()
        for ddl in SCHEMA_DDL:
            first_word = ddl.strip().split("\n")[0][:60]
            logger.debug("PostgreSQL >>> DDL: %s…", first_word)
            await self._pool.execute(ddl)
        dim = await self._check_vector_dim()
        logger.info(
            "PostgreSQL <<< схема проверена/создана за %.2fs, vector-размерность embedding=%s",
            time.perf_counter() - started, dim if dim is not None else "не задана",
        )
        if dim and dim != self._settings.embedding_dim:
            logger.error(
                "PostgreSQL <<< НЕСОВМЕСТИМОСТЬ СХЕМЫ: kb_embeddings.embedding = vector(%d), "
                "а EMBEDDING_DIM=%d — индексация/поиск будут падать",
                dim, self._settings.embedding_dim,
            )
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
        started = time.perf_counter()
        logger.info("PostgreSQL >>> healthcheck (SELECT 1, count kb_documents)…")
        try:
            row = await self.pool.fetchrow("SELECT 1 AS ok, (SELECT count(*) FROM kb_documents) AS docs")
            detail = f"documents={row['docs']}"
            logger.info("PostgreSQL <<< healthcheck OK за %.3fs: %s", time.perf_counter() - started, detail)
            return {"status": "ok", "detail": detail}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "PostgreSQL <<< healthcheck ПАДЕНИЕ за %.3fs (%s): %s — БД недоступна",
                time.perf_counter() - started, exc.__class__.__name__, exc,
            )
            return {"status": "down", "detail": f"{exc.__class__.__name__}: {exc}"}

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("Пул соединений закрыт")
