"""Репозиторий микросервиса news_analyzer: таблица ``market_news_ml_dataset``.

DDL зеркалирует init_db/02_init_market_news_ml.sql (идемпотентно, IF NOT EXISTS) —
как это делает app/db/database.py для RAG-таблиц, чтобы локальный запуск без
docker-entrypoint-initdb.d тоже работал.
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

NEWS_TABLE = "market_news_ml_dataset"

SCHEMA_DDL: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS pgcrypto",  # gen_random_uuid()
    f"""
    CREATE TABLE IF NOT EXISTS {NEWS_TABLE} (
        -- 1. Базовые поля (источник и новость)
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        source VARCHAR(255) NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        -- Используем TIMESTAMP(9) WITH TIME ZONE, чтобы сохранить наносекунды
        ts TIMESTAMP(9) WITH TIME ZONE NOT NULL,

        -- 2. Технические индикаторы (осцилляторы и метрики волатильности)
        rsi_14 DOUBLE PRECISION,
        stoch_k DOUBLE PRECISION,
        stoch_d DOUBLE PRECISION,
        macd DOUBLE PRECISION,
        macd_signal DOUBLE PRECISION,
        atr_14 DOUBLE PRECISION,

        -- 3. Числовая аналитика от ИИ (фичи для ML)
        ai_sentiment_score DOUBLE PRECISION,
        ai_relevance_score DOUBLE PRECISION,
        ai_expected_impact DOUBLE PRECISION,
        ai_confidence DOUBLE PRECISION,

        -- 4. Текстовая аналитика от ИИ
        ai_text_summary TEXT,
        ai_raw_response JSONB,

        -- 5. Целевые переменные (Target) для обучения классификации
        target_horizon_minutes INT NOT NULL DEFAULT 60,
        target_future_return_pct DOUBLE PRECISION,
        target_direction SMALLINT,
        target_volatility_threshold_pct DOUBLE PRECISION
    )
    """,
    f"CREATE INDEX IF NOT EXISTS idx_ml_dataset_ts ON {NEWS_TABLE} (ts DESC)",
)

_INSERT_SQL = f"""
    INSERT INTO {NEWS_TABLE} (source, title, content, ts)
    VALUES ($1, $2, $3, $4)
    RETURNING id, source, title, ts
"""


class NewsRepository:
    """Тонкая обёртка над живым пулом asyncpg (записи в датасет новостей)."""

    def __init__(self, pool_provider: Any) -> None:
        # pool_provider — объект с атрибутом .pool (app.db.database.Database):
        # ссылка на пул берётся в момент вызова, а не при сборке контейнера.
        self._pool_provider = pool_provider

    @property
    def _pool(self) -> asyncpg.Pool:
        return self._pool_provider.pool  # type: ignore[union-attr,no-any-return]

    async def ensure_schema(self) -> None:
        logger.info("news_analyzer >>> проверка схемы %s (%d DDL)…", NEWS_TABLE, len(SCHEMA_DDL))
        for ddl in SCHEMA_DDL:
            await self._pool.execute(ddl)
        logger.info("news_analyzer <<< схема %s готова", NEWS_TABLE)

    async def insert_news(self, *, source: str, title: str, content: str, ts) -> dict[str, Any]:
        row = await self._pool.fetchrow(_INSERT_SQL, source, title, content, ts)
        assert row is not None
        return dict(row)

    async def health(self) -> dict[str, str]:
        try:
            count = await self._pool.fetchval(f"SELECT count(*) FROM {NEWS_TABLE}")
            return {"status": "ok", "detail": f"{NEWS_TABLE} rows={count}"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "down", "detail": f"{exc.__class__.__name__}: {exc}"}
