"""Параметры для алгоритмов."""
from dataclasses import dataclass
from enum import StrEnum
from typing import List, Optional


class CandleInterval(StrEnum):
    """Интервалы свечей."""
    MINUTE = "CANDLE_INTERVAL_1_MIN"
    FIVE_MINUTES = "CANDLE_INTERVAL_5_MIN"
    FIFTEEN_MINUTES = "CANDLE_INTERVAL_15_MIN"
    HOUR = "CANDLE_INTERVAL_HOUR"
    DAY = "CANDLE_INTERVAL_DAY"


@dataclass
class AlgorithmDataRequest:
    """
    Запрос алгоритма на получение данных.
    
    Алгоритм возвращает этот объект, чтобы указать какие данные ему нужны.
    """
    instrument_id: str
    interval: CandleInterval
    limit: int = 100
    from_ts: Optional[str] = None
    to_ts: Optional[str] = None
    indicators: Optional[List[str]] = None


@dataclass
class AlgorithmParams:
    """Параметры для выполнения алгоритма."""
    instrument_id: str
    interval: CandleInterval
    limit: int = 100
    custom_params: Optional[dict] = None
