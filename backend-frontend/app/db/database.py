"""Пул asyncpg (паттерн python_test/app/db/database.py и scheduler_service).

backend-frontend — ТОЛЬКО ЧИТАТЕЛЬ таблицы ``market_news_ml_dataset``
(пишет n8n-workflow напрямую в БД), поэтому DDL здесь не создаётся:
схему обеспечивает docker-entrypoint-initdb.d (init_db/02_init_market_news_ml.sql).
При старте выполняется лишь проверка существования таблицы (fail-fast + понятный лог).
"""

from __future__ import annotations

import logging
import time
from urllib.parse import urlsplit, urlunsplit

import asyncpg

from app.core.config import Settings

logger = logging.getLogger(__name__)

# Проверка готовности схемы (таблица + таблицы стакана) — только чтение метаданных.
_SCHEMA_CHECK_SQL = """
    SELECT to_regclass('public.market_news_ml_dataset')  AS dataset,
           to_regclass('public.orderbook_asks')         AS asks,
           to_regclass('public.orderbook_bids')         AS bids
"""


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

        # Fail-fast: без таблицы фронтам отдавать нечего — но не падать, а предупредить.
        row = await self._pool.fetchrow(_SCHEMA_CHECK_SQL)
        if row and row["dataset"]:
            logger.info("PostgreSQL <<< таблица market_news_ml_dataset найдена")
        else:
            logger.warning(
                "PostgreSQL <<< ВНИМАНИЕ: таблица market_news_ml_dataset НЕ найдена "
                "(ожидается init_db/02_init_market_news_ml.sql) — эндпоинты вернут пустые данные"
            )

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
