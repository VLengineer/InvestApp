"""Параметры для компонента data_provider."""
from dataclasses import dataclass
from typing import List, Optional

from schemas.market_data import IndicatorType


@dataclass
class DataProviderParams:
    """Параметры для загрузки данных."""
    instrument_id: str  # FIGI
    from_ts: str  # ISO timestamp
    to_ts: str  # ISO timestamp
    candle_interval: str = "CANDLE_INTERVAL_5_MIN"
    indicators_interval: str = "INDICATOR_INTERVAL_FIVE_MINUTES"
    indicator_length: int = 14
    price_types: Optional[List[str]] = None
    indicator_types: Optional[List[IndicatorType]] = None
    
    def __post_init__(self):
        if self.price_types is None:
            self.price_types = [
                "TYPE_OF_PRICE_CLOSE",
                "TYPE_OF_PRICE_OPEN",
                "TYPE_OF_PRICE_HIGH",
                "TYPE_OF_PRICE_LOW",
                "TYPE_OF_PRICE_AVG",
            ]
        if self.indicator_types is None:
            self.indicator_types = list(IndicatorType)
