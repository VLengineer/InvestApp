"""Pydantic-модели запроса/ответа эндпоинта POST /indicators/calculate.

Вход — массив свечей в формате T-Invest API (``units`` + ``nano``),
выход — пострядовые технические индикаторы + аналитика + метаданные.
Схема ответа точно соответствует ТЗ (раздел 2.1).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------
class Money(BaseModel):
    """Деньги в формате T-Invest API: ``{"units": "296", "nano": 790000000}``."""

    model_config = ConfigDict(extra="ignore")

    units: str | int | float = Field(description="Целая часть цены")
    nano: int | float = Field(default=0, description="Наночасть цены (1e-9)")


class CandleIn(BaseModel):
    """Свеча T-Invest API (GetCandles)."""

    model_config = ConfigDict(extra="ignore")

    open: Money = Field(description="Цена открытия")
    high: Money = Field(description="Максимум")
    low: Money = Field(description="Минимум")
    close: Money = Field(description="Цена закрытия")
    volume: str | int | float = Field(default=0, description="Объём в лотах")
    time: str = Field(description="Время свечи, ISO 8601 (…T18:25:00Z)")
    isComplete: bool = Field(default=True, description="Завершена ли свеча")
    candleSource: Optional[str] = Field(default=None, description="Источник свечи")
    volumeBuy: Optional[str | int | float] = Field(default=None, description="Объём покупок")
    volumeSell: Optional[str | int | float] = Field(default=None, description="Объём продаж")


class IndicatorsRequest(BaseModel):
    """Тело запроса: массив свечей (минимум 40 — warmup period)."""

    model_config = ConfigDict(extra="ignore")

    candles: list[CandleIn] = Field(
        min_length=1,
        description=(
            "Свечи в формате T-Invest API. Минимум 40 свечей для расчёта индикаторов; "
            "несортированные данные сортируются автоматически."
        ),
    )


# ---------------------------------------------------------------------------
# Response: indicators
# ---------------------------------------------------------------------------
class IndicatorRow(BaseModel):
    """Набор индикаторов для одной свечи (для warmup-свечей значения могут быть null)."""

    timestamp: str
    rsi_14: Optional[float] = None
    stoch_k: Optional[float] = None
    stoch_d: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    cci_20: Optional[float] = None
    williams_r: Optional[float] = None
    mfi_14: Optional[float] = None
    adx_14: Optional[float] = None
    roc_12: Optional[float] = None
    atr_14: Optional[float] = None
    is_valid: bool = Field(description="False для первых 40 свечей (warmup period)")


# ---------------------------------------------------------------------------
# Response: analytics
# ---------------------------------------------------------------------------
class GapInfo(BaseModel):
    timestamp: str
    gap_percent: float
    direction: str = Field(description="'up' или 'down'")
    severity: str = Field(description="'low' (<0.1%), 'medium' (0.1–0.3%), 'high' (>0.3%)")


class VolumeAnomaly(BaseModel):
    timestamp: str
    volume: float
    avg_volume_20: float
    anomaly_ratio: float = Field(description="Во сколько раз объём превышает средний")
    direction: str = Field(description="'buy' если volumeBuy > volumeSell, иначе 'sell'")


class TrendInfo(BaseModel):
    start_timestamp: str
    end_timestamp: str
    duration_candles: int
    price_change_percent: float
    direction: str = Field(description="'up' или 'down'")
    strength: str = Field(description="'weak' (<0.2%), 'medium' (0.2–0.5%), 'strong' (>0.5%)")


class CandlePattern(BaseModel):
    timestamp: str
    pattern: str = Field(
        description=(
            "'bullish_engulfing', 'bearish_engulfing', 'hammer', 'inverted_hammer', 'doji'"
        )
    )
    confidence: float = Field(ge=0.0, le=1.0)


class VolatilityRegime(BaseModel):
    current_atr: Optional[float] = None
    avg_atr_20: Optional[float] = None
    regime: str = Field(
        description="'low_volatility' (<0.8x), 'normal' (0.8–1.2x), 'high_volatility' (>1.2x)"
    )
    ratio: Optional[float] = None


class MomentumInfo(BaseModel):
    current: Optional[float] = None
    acceleration: Optional[float] = None
    regime: str = Field(
        description=(
            "'bullish_acceleration' | 'bullish_deceleration' | 'bearish_acceleration' "
            "| 'bearish_deceleration' | 'neutral'"
        )
    )


class AnalyticsResponse(BaseModel):
    gaps: list[GapInfo] = []
    volume_anomalies: list[VolumeAnomaly] = []
    trends: list[TrendInfo] = []
    candle_patterns: list[CandlePattern] = []
    volatility_regime: VolatilityRegime
    momentum: MomentumInfo


class IndicatorsMetadata(BaseModel):
    total_candles: int
    valid_candles: int
    warmup_period: int = 40
    timeframe_minutes: int
    calculation_time_ms: int


class LastCandleRSI(BaseModel):
    """RSI(14) последней свечи из принятого JSON (удобное поле для быстрого чтения)."""

    timestamp: str = Field(description="Время последней свечи (после авто-сортировки по времени)")
    rsi_14: Optional[float] = Field(default=None, description="Значение RSI(14), null если не рассчитан")


class IndicatorsResponse(BaseModel):
    indicators: list[IndicatorRow]
    analytics: AnalyticsResponse
    metadata: IndicatorsMetadata
    last_candle_rsi: LastCandleRSI = Field(
        description="RSI(14) для последней свечи входного набора данных"
    )
