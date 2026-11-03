"""Модель строки таблицы ``market_news_ml_dataset`` (SQLAlchemy Core, declarative-free).

Таблица принадлежит микросервису news_analyzer/n8n (пишет напрямую в БД);
backend-frontend — единственный читатель для Vue-фронта. Колонки зеркалят
DDL init_db/02_init_market_news_ml.sql и init_db/table_field.json.

Используется SQLAlchemy Core Table (не ORM): выборки идут через asyncpg-пул
сырым SQL (паттерн остальных сервисов проекта), а метаданные таблицы служат
единым источником имён колонок для репозитория и Pydantic-схем.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, Integer, MetaData, Numeric, String, Table, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

market_news_ml_dataset = Table(
    "market_news_ml_dataset",
    metadata,
    # 1. Базовые поля (источник и новость)
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("figi", String(32)),
    Column("source", String(255)),
    Column("title", Text),
    Column("content", Text),
    Column("ts", DateTime(timezone=True)),
    Column("candle_time", DateTime(timezone=True)),
    # 2. Данные свечи (OHLCV)
    Column("open_price", Float, nullable=False),
    Column("high_price", Float, nullable=False),
    Column("low_price", Float, nullable=False),
    Column("close_price", Float, nullable=False),
    Column("volume", Integer, nullable=False),
    Column("volume_buy", Integer, nullable=False),
    Column("volume_sell", Integer, nullable=False),
    Column("is_complete", Integer),
    # 3. Технические индикаторы
    Column("rsi_14", Float, nullable=False),
    Column("stoch_k", Float, nullable=False),
    Column("stoch_d", Float, nullable=False),
    Column("cci_20", Float, nullable=False),
    Column("williams_r", Float, nullable=False),
    Column("roc_12", Float, nullable=False),
    Column("mfi_14", Float, nullable=False),
    Column("macd", Float, nullable=False),
    Column("macd_signal", Float, nullable=False),
    Column("adx_14", Float, nullable=False),
    Column("atr_14", Float, nullable=False),
    # 3b. Рыночные данные Tinkoff Invest API
    Column("limit_up_units", Float, nullable=False),
    Column("limit_down_units", Float, nullable=False),
    Column("close_price_units", Float, nullable=False),
    Column("last_price_units", Float, nullable=False),
    Column("price_currency", String(16), nullable=False),
    Column("last_price_ts", DateTime(timezone=True)),
    Column("orderbook_ts", DateTime(timezone=True)),
    Column("close_price_ts", DateTime(timezone=True)),
    Column("depth", Integer),
    # 4. Числовая аналитика от ИИ
    Column("ai_sentiment_score", Float),
    Column("ai_relevance_score", Float),
    Column("ai_expected_impact", Float),
    Column("ai_confidence", Float),
    # 5. Текстовая аналитика от ИИ
    Column("ai_text_summary", Text),
    Column("ai_raw_response", JSONB),
    # 6. Целевые переменные (Target) для ML
    Column("target_horizon_minutes", Integer, nullable=False, server_default=func.cast(60, Numeric)),
    Column("target_future_return_pct", Float),
    Column("target_direction", Integer),
    Column("target_volatility_threshold_pct", Float),
)

# Порядок колонок для SELECT * (используется репозиторием как единый список имён).
ALL_COLUMNS: tuple[str, ...] = tuple(c.name for c in market_news_ml_dataset.columns)
