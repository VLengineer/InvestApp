"""Пул asyncpg + идемпотентная инициализация схемы (паттерн python_test/app/db/database.py).

Таблицы в проде создаёт docker-entrypoint-initdb.d (init_db/04_init_scheduler.sql);
здесь та же DDL нужна для локального запуска/тестов против обычной PostgreSQL.
Всё IF NOT EXISTS — повторный старт безопасен.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import urlsplit, urlunsplit

import asyncpg

from app.core.config import Settings

logger = logging.getLogger(__name__)

# Единая точка определения DDL микросервиса; зеркалит init_db/04_init_scheduler.sql.
SCHEMA_DDL: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS pgcrypto",  # gen_random_uuid()
    """
    CREATE TABLE IF NOT EXISTS scheduler_state (
        id        INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- singleton-строка
        is_active BOOLEAN NOT NULL DEFAULT TRUE
    )
    """,
    # Один гарантированный стартовый ряд: планировщик активен по умолчанию.
    "INSERT INTO scheduler_state (id, is_active) VALUES (1, TRUE) ON CONFLICT (id) DO NOTHING",
    # Единая точка определения DDL микросервиса; зеркалит init_db/04_init_scheduler.sql.
    # Модель очереди FIFO: waiting -> processing (воркер) -> completed|error (n8n callback).
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        status     VARCHAR(16) NOT NULL DEFAULT 'waiting'
                   CHECK (status IN ('waiting', 'processing', 'completed', 'error')),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks (status)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_created_at ON tasks (created_at DESC)",
    # Миграция старых баз (pending/rejected -> waiting/error), идемпотентно.
    "UPDATE tasks SET status = 'waiting', updated_at = now() WHERE status = 'pending'",
    "UPDATE tasks SET status = 'error', updated_at = now() WHERE status = 'rejected'",
)


def _dsn_masked(dsn: str) -> str:
    """Показываем хост/порт/БД без пароля (пароль секрет)."""
    try:
        parts = urlsplit(dsn)
        host = parts.hostname or "?"
        netloc = f"***:***@{host}:{parts.port}" if parts.password else f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except Exception:  # noqa: BLE001
        return "<dsn скрыт>"


class Database:
    """Тонкая обёртка над пулом соединений asyncpg."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is not None:
            return
        target = _dsn_masked(self._settings.dsn)
        logger.info("PostgreSQL >>> подключение к %s (pool=%d..%d)",
                    target, self._settings.db_pool_min_size, self._settings.db_pool_max_size)
        started = time.perf_counter()
        try:
            self._pool = await asyncpg.create_pool(
                dsn=self._settings.dsn,
                min_size=self._settings.db_pool_min_size,
                max_size=self._settings.db_pool_max_size,
                server_settings={"application_name": self._settings.app_name},
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("PostgreSQL <<< ОШИБКА подключения к %s: %s", target, exc)
            raise
        logger.info("PostgreSQL <<< OK за %.2fs: пул создан к %s", time.perf_counter() - started, target)

    async def ensure_schema(self) -> None:
        """Идемпотентная проверка/создание таблиц (для локального запуска без init_db)."""
        assert self._pool is not None, "Database.connect() не вызван"
        for ddl in SCHEMA_DDL:
            await self._pool.execute(ddl)
        logger.info("PostgreSQL <<< схема scheduler проверена/создана (%d DDL)", len(SCHEMA_DDL))

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Пул соединений не инициализирован")
        return self._pool

    async def health(self) -> dict[str, str]:
        try:
            row = await self.pool.fetchrow("SELECT 1 AS ok")
            return {"status": "ok", "detail": f"SELECT 1 -> {row['ok']}"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "down", "detail": f"{exc.__class__.__name__}: {exc}"}

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("Пул соединений закрыт")
