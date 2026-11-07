"""Схемы запросов/ответов рынка (паттерн python_test/app/schemas + scheduler_service).

``MarketDataItem`` — ровно одна строка таблицы ``market_news_ml_dataset``
(все колонки DDL init_db/02_init_market_news_ml.sql). Даты всегда отдаются
в UTC в ISO-8601 (LiteCharts/ECharts на фронте конвертируют в unix-секунды).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OrderBookLevel(BaseModel):
    """Одна заявка стакана (orderbook_asks / orderbook_bids)."""

    position: int = Field(description="Позиция в стакане (1, 2, 3...)")
    price: float = Field(description="Цена заявки (units + nano/1e9)")
    quantity: float = Field(description="Количество (лоты/штуки)")


class MarketDataItem(BaseModel):
    """Строка market_news_ml_dataset — базовая единица данных фронта."""

    model_config = ConfigDict(from_attributes=True)

    # 1. Базовые поля (источник и новость)
    id: UUID
    figi: str | None = None
    source: str | None = None
    title: str | None = None
    content: str | None = None
    ts: datetime | None = None
    candle_time: datetime | None = None

    # 2. Данные свечи (OHLCV)
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int
    volume_buy: int
    volume_sell: int
    is_complete: bool | None = None

    # 3. Технические индикаторы (осцилляторы + тренд/волатильность)
    rsi_14: float
    stoch_k: float
    stoch_d: float
    cci_20: float
    williams_r: float
    roc_12: float
    mfi_14: float
    macd: float
    macd_signal: float
    adx_14: float
    atr_14: float

    # 3b. Рыночные данные Tinkoff Invest API
    limit_up_units: float
    limit_down_units: float
    close_price_units: float
    last_price_units: float
    price_currency: str
    last_price_ts: datetime | None = None
    orderbook_ts: datetime | None = None
    close_price_ts: datetime | None = None
    depth: int | None = None

    # 4/5. Аналитика от ИИ
    ai_sentiment_score: float | None = None
    ai_relevance_score: float | None = None
    ai_expected_impact: float | None = None
    ai_confidence: float | None = None
    ai_text_summary: str | None = None
    ai_raw_response: dict[str, Any] | None = None

    # 6. Целевые переменные (Target) для ML
    target_horizon_minutes: int
    target_future_return_pct: float | None = None
    target_direction: int | None = None
    target_volatility_threshold_pct: float | None = None

    # Стакан (дополняется сервисом из orderbook_asks/orderbook_bids; не колонка таблицы)
    orderbook_asks: list[OrderBookLevel] = Field(default_factory=list)
    orderbook_bids: list[OrderBookLevel] = Field(default_factory=list)


# ------------------------------- Ответы REST --------------------------------

class FigiListResponse(BaseModel):
    """GET /api/market/figis — список уникальных FIGI, по которым есть данные."""

    figis: list[str]


class InitialDataResponse(BaseModel):
    """GET /api/market/initial-data?figi=... — последние N записей по FIGI."""

    data: list[MarketDataItem]
    figi: str


class NewsResponse(BaseModel):
    """GET /api/market/news/{id} — полная информация о новости по ID."""

    news: MarketDataItem


class AllNewsListResponse(BaseModel):
    """GET /api/market/all-news — все новости с пагинацией."""

    items: list[MarketDataItem]
    total: int
    limit: int
    offset: int


class HealthResponse(BaseModel):
    """GET /live, /ready — liveness/readiness (паттерн scheduler_service)."""

    status: str
    app: str
    version: str
    environment: str
    checks: dict[str, str] = Field(default_factory=dict)
