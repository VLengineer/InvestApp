"""Схемы для рыночных данных."""
from enum import StrEnum
from typing import Dict, Optional

from pydantic import BaseModel, Field


class Quotation(BaseModel):
    """Представление цены из API."""
    units: str
    nano: int
    
    def to_float(self) -> float:
        """Преобразует Quotation в float."""
        return float(self.units) + (float(self.nano) / 1e9)


class Candle(BaseModel):
    """Свеча."""
    open: Quotation
    high: Quotation
    low: Quotation
    close: Quotation
    volume: str
    time: str
    is_complete: bool = Field(alias="isComplete")
    
    model_config = {"populate_by_name": True}


class TechIndicator(BaseModel):
    """Технический индикатор."""
    timestamp: str
    signal: Optional[Quotation] = None
    upper_band: Optional[Quotation] = Field(default=None, alias="upperBand")
    middle_band: Optional[Quotation] = Field(default=None, alias="middleBand")
    lower_band: Optional[Quotation] = Field(default=None, alias="lowerBand")
    macd: Optional[Quotation] = None
    
    model_config = {"populate_by_name": True}


class MarketSnapshot(BaseModel):
    """
    Единая строка данных для обучения ML-модели.
    
    indicators хранит данные для всех типов цены и индикаторов:
    indicators["TYPE_OF_PRICE_CLOSE"]["bb"] = TechIndicator(...)
    indicators["TYPE_OF_PRICE_OPEN"]["ema"] = TechIndicator(...)
    """
    timestamp: str
    candle: Optional[Candle] = None
    indicators: Dict[str, Dict[str, Optional[TechIndicator]]] = Field(default_factory=dict)


class IndicatorType(StrEnum):
    """Типы технических индикаторов."""
    BB = "INDICATOR_TYPE_BB"
    EMA = "INDICATOR_TYPE_EMA"
    RSI = "INDICATOR_TYPE_RSI"
    MACD = "INDICATOR_TYPE_MACD"
    SMA = "INDICATOR_TYPE_SMA"


ALL_INDICATOR_TYPES = list(IndicatorType)
