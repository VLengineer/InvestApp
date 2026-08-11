"""Domain models for News Market Analyzer."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import List, Dict
from uuid import UUID


@dataclass
class Asset:
    figi: str
    ticker: str
    class_code: str
    instrument_type: str


@dataclass
class PriceLevel:
    price: Decimal
    quantity: int


@dataclass
class OrderBook:
    bids: List[PriceLevel] = field(default_factory=list)
    asks: List[PriceLevel] = field(default_factory=list)
    spread: Decimal = Decimal("0")
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Currency:
    code: str
    rate_to_rub: Decimal


@dataclass
class Features:
    rsi: float = 0.0
    macd: float = 0.0
    sma_20: float = 0.0
    sma_50: float = 0.0
    ema_12: float = 0.0
    atr: float = 0.0
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    volatility: float = 0.0


@dataclass
class Candle:
    dt: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    order_book: OrderBook
    currency: Currency
    features: Features


@dataclass
class Timeframe:
    asset: Asset
    candles: List[Candle] = field(default_factory=list)


@dataclass
class NewsItem:
    id: UUID
    title: str
    body: str
    source: str
    published_at: datetime
    url: str


@dataclass
class NewsAnalysisItem:
    news: NewsItem
    classification: str
    analytics: str
    impact_scores: Dict[str, float] = field(default_factory=dict)
    timeframe: Timeframe = None
