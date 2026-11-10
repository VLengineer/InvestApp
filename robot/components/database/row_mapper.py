"""Маппинг MarketSnapshot в строки БД."""
from typing import Dict, Optional

from schemas.market_data import MarketSnapshot, TechIndicator
from common.time_utils import parse_iso_timestamp
from components.data_provider.mappers import PRICE_TYPES, PRICE_TYPE_PREFIX


def _indicator_to_db_fields(
    ind: Optional[TechIndicator], prefix: str, ind_name: str
) -> Dict[str, Optional[float]]:
    """Маппит один TechIndicator в поля БД с учётом типа индикатора."""
    result: Dict[str, Optional[float]] = {}
    
    if ind_name == "bb":
        result[f"{prefix}_bb_upper"] = ind.upper_band.to_float() if ind and ind.upper_band else None
        result[f"{prefix}_bb_middle"] = ind.middle_band.to_float() if ind and ind.middle_band else None
        result[f"{prefix}_bb_lower"] = ind.lower_band.to_float() if ind and ind.lower_band else None
    elif ind_name == "ema":
        result[f"{prefix}_ema_signal"] = ind.signal.to_float() if ind and ind.signal else None
    elif ind_name == "rsi":
        result[f"{prefix}_rsi_signal"] = ind.signal.to_float() if ind and ind.signal else None
    elif ind_name == "sma":
        result[f"{prefix}_sma_signal"] = ind.signal.to_float() if ind and ind.signal else None
    elif ind_name == "macd":
        result[f"{prefix}_macd_value"] = ind.macd.to_float() if ind and ind.macd else None
        result[f"{prefix}_macd_signal"] = ind.signal.to_float() if ind and ind.signal else None
    
    return result


def snapshot_to_db_row(snapshot: MarketSnapshot, figi: str) -> dict:
    """Преобразует MarketSnapshot в плоский словарь для INSERT в PostgreSQL."""
    c = snapshot.candle
    
    row = {
        "timestamp": parse_iso_timestamp(snapshot.timestamp),
        "figi": figi,
        "candle_open": c.open.to_float() if c else None,
        "candle_high": c.high.to_float() if c else None,
        "candle_low": c.low.to_float() if c else None,
        "candle_close": c.close.to_float() if c else None,
        "candle_volume": int(c.volume) if c else None,
        "candle_is_complete": c.is_complete if c else None,
    }
    
    # Заполняем индикаторы для всех типов цены
    for price_type in PRICE_TYPES:
        prefix = PRICE_TYPE_PREFIX[price_type]
        type_indicators = snapshot.indicators.get(price_type, {})
        for ind_name in ("bb", "ema", "rsi", "sma", "macd"):
            ind = type_indicators.get(ind_name)
            row.update(_indicator_to_db_fields(ind, prefix, ind_name))
    
    # Обратная совместимость: заполняем старые колонки (без префикса) из close
    close_indicators = snapshot.indicators.get("TYPE_OF_PRICE_CLOSE", {})
    bb = close_indicators.get("bb")
    ema = close_indicators.get("ema")
    rsi = close_indicators.get("rsi")
    macd = close_indicators.get("macd")
    sma = close_indicators.get("sma")
    
    row["bb_upper"] = bb.upper_band.to_float() if bb and bb.upper_band else None
    row["bb_middle"] = bb.middle_band.to_float() if bb and bb.middle_band else None
    row["bb_lower"] = bb.lower_band.to_float() if bb and bb.lower_band else None
    row["ema_signal"] = ema.signal.to_float() if ema and ema.signal else None
    row["sma_signal"] = sma.signal.to_float() if sma and sma.signal else None
    row["rsi_signal"] = rsi.signal.to_float() if rsi and rsi.signal else None
    row["macd_value"] = macd.macd.to_float() if macd and macd.macd else None
    row["macd_signal"] = macd.signal.to_float() if macd and macd.signal else None
    
    return row
