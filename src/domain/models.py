"""Domain models for News Market Analyzer."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ImpactScores(BaseModel):
    """Market impact scores from news analysis."""
    
    market_sentiment: float = Field(
        default=0.0,
        description="Overall market sentiment score (-1.0 to 1.0)",
        ge=-1.0,
        le=1.0
    )
    volatility_impact: float = Field(
        default=0.0,
        description="Expected volatility impact (0.0 to 1.0)",
        ge=0.0,
        le=1.0
    )
    volume_impact: float = Field(
        default=0.0,
        description="Expected trading volume impact (0.0 to 1.0)",
        ge=0.0,
        le=1.0
    )
    sector_impact: float = Field(
        default=0.0,
        description="Sector-specific impact score (-1.0 to 1.0)",
        ge=-1.0,
        le=1.0
    )
    short_term_effect: float = Field(
        default=0.0,
        description="Short-term price effect prediction (-1.0 to 1.0)",
        ge=-1.0,
        le=1.0
    )
    medium_term_effect: float = Field(
        default=0.0,
        description="Medium-term price effect prediction (-1.0 to 1.0)",
        ge=-1.0,
        le=1.0
    )
    confidence_score: float = Field(
        default=0.0,
        description="Confidence in the analysis (0.0 to 1.0)",
        ge=0.0,
        le=1.0
    )

    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> "ImpactScores":
        """Create from dictionary."""
        return cls(**data)


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
class Timeframe:
    asset: Asset
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
class Candle:
    """Candle data with OHLCV and additional info."""
    dt: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    order_book: OrderBook = field(default_factory=OrderBook)
    currency: Currency = None
    features: Features = field(default_factory=Features)


@dataclass
class NewsItem:
    id: UUID
    title: str
    body: str
    source: str
    published_at: datetime
    url: str


@dataclass
class NewsAnalysisResult:
    """Результат анализа новости."""
    news: NewsItem
    scores: ImpactScores
    analysis_text: str
    classification: str = "neutral"


@dataclass
class NewsAnalysisItem:
    news: NewsItem
    classification: str
    analytics: str
    impact_scores: ImpactScores = field(default_factory=ImpactScores)
    timeframe: Optional[Timeframe] = None
