import os
import asyncio
import logging
import warnings
from enum import StrEnum
from pathlib import Path
from typing import List, Optional, Dict

import httpx
import urllib3
import asyncpg
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Подавляем warning о невалидном SSL-сертификате
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Загрузка .env из директории скрипта ---
load_dotenv(Path(__file__).parent / ".env")

# --- Константы ---
TOKEN = os.getenv("TINVEST_TOKEN", "")
FIGI = os.getenv("FIGI", "BBG004730N88")
FROM_TS = "2024-11-10T00:00:00Z"
TO_TS = "2026-11-10T23:59:59Z"
CANDLE_INTERVAL = "CANDLE_INTERVAL_5_MIN"
INDICATORS_INTERVAL = "INDICATOR_INTERVAL_FIVE_MINUTES"
INDICATOR_LENGTH = 14  # Стандартный период для RSI/EMA/SMA
BASE_URL = "https://invest-public-api.tbank.ru/rest"

# Все типы цены для сбора индикаторов
PRICE_TYPES = [
    "TYPE_OF_PRICE_CLOSE",
    "TYPE_OF_PRICE_OPEN",
    "TYPE_OF_PRICE_HIGH",
    "TYPE_OF_PRICE_LOW",
    "TYPE_OF_PRICE_AVG",
]

# Маппинг типа цены к короткому префиксу для колонок БД
PRICE_TYPE_PREFIX = {
    "TYPE_OF_PRICE_CLOSE": "close",
    "TYPE_OF_PRICE_OPEN": "open",
    "TYPE_OF_PRICE_HIGH": "high",
    "TYPE_OF_PRICE_LOW": "low",
    "TYPE_OF_PRICE_AVG": "avg",
}

# --- PostgreSQL ---
DATABASE_URL = os.getenv("DATABASE_URL") or (
    f"postgresql://{os.getenv('POSTGRES_USER', 'change_me_user')}"
    f":{os.getenv('POSTGRES_PASSWORD', 'change_me_strong_password')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}"
    f":{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB', 'vectordb')}"
)

logger = logging.getLogger(__name__)


class IndicatorType(StrEnum):
    BB = "INDICATOR_TYPE_BB"
    EMA = "INDICATOR_TYPE_EMA"
    RSI = "INDICATOR_TYPE_RSI"
    MACD = "INDICATOR_TYPE_MACD"
    SMA = "INDICATOR_TYPE_SMA"


ALL_INDICATOR_TYPES = list(IndicatorType)


class Quotation(BaseModel):
    units: str
    nano: int

    def to_float(self) -> float:
        """Удобный метод для ML: преобразует Quotation в float"""
        return float(self.units) + (float(self.nano) / 1e9)


class Candle(BaseModel):
    open: Quotation
    high: Quotation
    low: Quotation
    close: Quotation
    volume: str
    time: str
    is_complete: bool = Field(alias="isComplete")
    
    model_config = {"populate_by_name": True}


# --- Модели индикаторов (все поля Optional, т.к. API возвращает только запрошенные) ---
class TechIndicator(BaseModel):
    timestamp: str
    signal: Optional[Quotation] = None
    upper_band: Optional[Quotation] = Field(default=None, alias="upperBand")
    middle_band: Optional[Quotation] = Field(default=None, alias="middleBand")
    lower_band: Optional[Quotation] = Field(default=None, alias="lowerBand")
    macd: Optional[Quotation] = None

    model_config = {"populate_by_name": True}


# --- Итоговый снимок данных для ML (Wide Format) ---
class MarketSnapshot(BaseModel):
    """Единая строка данных для обучения ML-модели.
    
    indicators хранит данные для всех типов цены и индикаторов:
    indicators["TYPE_OF_PRICE_CLOSE"]["bb"] = TechIndicator(...)
    indicators["TYPE_OF_PRICE_OPEN"]["ema"] = TechIndicator(...)
    """
    timestamp: str
    candle: Optional[Candle] = None
    indicators: Dict[str, Dict[str, Optional[TechIndicator]]] = Field(default_factory=dict)


async def fetch_candles(instrument_id: str, from_ts: str, to_ts: str, interval: str) -> Dict[str, Candle]:
    url = f"{BASE_URL}/tinkoff.public.invest.api.contract.v1.MarketDataService/GetCandles"
    payload = {"instrumentId": instrument_id, "from": from_ts, "to": to_ts, "interval": interval}
    async with httpx.AsyncClient(verify=False) as client:
        resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {TOKEN}"})
        resp.raise_for_status()
        data = resp.json()
    
    # Ключ словаря - timestamp для быстрого merge
    return {c["time"]: Candle(**c) for c in data.get("candles", [])}


async def fetch_indicators(
    instrument_id: str, from_ts: str, to_ts: str, interval: str, price_type: str, length: int, ind_type: IndicatorType
) -> Dict[str, TechIndicator]:
    url = f"{BASE_URL}/tinkoff.public.invest.api.contract.v1.MarketDataService/GetTechAnalysis"
    
    # Базовый payload для всех индикаторов
    payload = {
        "indicatorType": ind_type.value,
        "instrumentId": instrument_id,
        "from": from_ts,
        "to": to_ts,
        "interval": interval,
        "typeOfPrice": price_type,
        "length": length,
    }
    
    # Дополнительные параметры для специфичных индикаторов
    if ind_type == IndicatorType.BB:
        # Bollinger Bands требует параметр deviation в формате Quotation
        payload["deviation"] = {
            "deviationMultiplier": {
                "units": "2",
                "nano": 0
            }
        }
    elif ind_type == IndicatorType.MACD:
        # MACD требует параметр smoothing_data с настройками сглаживания
        payload["smoothingData"] = {
            "shortPeriod": 12,
            "longPeriod": 26,
            "signalSmoothing": 9
        }
    
    logger.debug(f"Fetching {ind_type.value} with payload: {payload}")
    
    async with httpx.AsyncClient(verify=False) as client:
        resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {TOKEN}"})
        if resp.status_code != 200:
            logger.error(f"Error fetching {ind_type.value}: {resp.status_code}")
            logger.error(f"Request payload: {payload}")
            logger.error(f"Response body: {resp.text}")
            raise Exception(f"API error {resp.status_code} for {ind_type.value}: {resp.text}")
        data = resp.json()
    
    return {item["timestamp"]: TechIndicator(**item) for item in data.get("technicalIndicators", [])}


async def build_ml_dataset(instrument_id: str, from_ts: str, to_ts: str) -> List[MarketSnapshot]:
    """Собирает все данные для всех типов цены и объединяет их по timestamp."""
    
    # 1. Формируем задачи: свечи + все комбинации (тип цены × индикатор)
    tasks: list = [fetch_candles(instrument_id, from_ts, to_ts, CANDLE_INTERVAL)]
    
    for price_type in PRICE_TYPES:
        for ind_type in ALL_INDICATOR_TYPES:
            tasks.append(
                fetch_indicators(
                    instrument_id, from_ts, to_ts,
                    INDICATORS_INTERVAL, price_type, INDICATOR_LENGTH, ind_type,
                )
            )
    
    # 2. Запускаем все запросы параллельно (1 свечи + 25 индикаторов = 26 задач)
    results = await asyncio.gather(*tasks)
    
    candles = results[0]
    
    # 3. Группируем результаты индикаторов: {price_type: {indicator_name: {ts: TechIndicator}}}
    indicator_data: Dict[str, Dict[str, Dict[str, TechIndicator]]] = {}
    idx = 1
    for price_type in PRICE_TYPES:
        indicator_data[price_type] = {}
        for ind_type in ALL_INDICATOR_TYPES:
            indicator_data[price_type][ind_type.name.lower()] = results[idx]
            idx += 1
    
    # 4. Собираем все уникальные timestamp
    all_timestamps = set(candles.keys())
    for price_type in PRICE_TYPES:
        for ind_name, ind_dict in indicator_data[price_type].items():
            all_timestamps |= set(ind_dict.keys())
    all_timestamps = sorted(all_timestamps)
    
    # 5. Формируем итоговые снимки
    snapshots = []
    for ts in all_timestamps:
        # Собираем индикаторы для каждого типа цены
        indicators: Dict[str, Dict[str, Optional[TechIndicator]]] = {}
        for price_type in PRICE_TYPES:
            indicators[price_type] = {}
            for ind_type in ALL_INDICATOR_TYPES:
                ind_name = ind_type.name.lower()
                indicators[price_type][ind_name] = indicator_data[price_type][ind_name].get(ts)
        
        snapshot = MarketSnapshot(
            timestamp=ts,
            candle=candles.get(ts),
            indicators=indicators,
        )
        snapshots.append(snapshot)
        
    return snapshots


def _extract_indicator_fields(ind: Optional[TechIndicator], prefix: str) -> Dict[str, Optional[float]]:
    """Извлекает числовые поля индикатора с заданным префиксом для колонок БД."""
    if ind is None:
        return {
            f"{prefix}_bb_upper": None,
            f"{prefix}_bb_middle": None,
            f"{prefix}_bb_lower": None,
            f"{prefix}_ema_signal": None,
            f"{prefix}_rsi_signal": None,
            f"{prefix}_sma_signal": None,
            f"{prefix}_macd_value": None,
            f"{prefix}_macd_signal": None,
        }
    # Для BB-индикатора используются upper_band/middle_band/lower_band
    # Для EMA/RSI/SMA — signal
    # Для MACD — macd и signal
    # Но мы вызываем эту функцию для каждого индикатора отдельно,
    # поэтому нужно понять, какой именно индикатор передан.
    # Используем универсальный подход: возвращаем все поля, которые не None.
    return {
        f"{prefix}_bb_upper": ind.upper_band.to_float() if ind.upper_band else None,
        f"{prefix}_bb_middle": ind.middle_band.to_float() if ind.middle_band else None,
        f"{prefix}_bb_lower": ind.lower_band.to_float() if ind.lower_band else None,
        f"{prefix}_ema_signal": ind.signal.to_float() if ind.signal else None,
        f"{prefix}_rsi_signal": ind.signal.to_float() if ind.signal else None,
        f"{prefix}_sma_signal": ind.signal.to_float() if ind.signal else None,
        f"{prefix}_macd_value": ind.macd.to_float() if ind.macd else None,
        f"{prefix}_macd_signal": ind.signal.to_float() if ind.signal else None,
    }


def _indicator_to_db_fields(
    ind: Optional[TechIndicator], prefix: str, ind_name: str
) -> Dict[str, Optional[float]]:
    """Маппит один TechIndicator в поля БД с учётом типа индикатора.
    
    BB  -> {prefix}_bb_upper, {prefix}_bb_middle, {prefix}_bb_lower
    EMA -> {prefix}_ema_signal
    RSI -> {prefix}_rsi_signal
    SMA -> {prefix}_sma_signal
    MACD -> {prefix}_macd_value, {prefix}_macd_signal
    """
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


def snapshot_to_db_row(snapshot: MarketSnapshot, figi: str = FIGI) -> dict:
    """Преобразует сложный объект в плоский словарь для INSERT в PostgreSQL."""
    c = snapshot.candle
    
    row = {
        "timestamp": snapshot.timestamp,
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


# --- Database functions ---

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS robot_market_data (
    timestamp         TIMESTAMPTZ      NOT NULL,
    figi              VARCHAR(32)      NOT NULL,
    candle_open       DOUBLE PRECISION,
    candle_high       DOUBLE PRECISION,
    candle_low        DOUBLE PRECISION,
    candle_close      DOUBLE PRECISION,
    candle_volume     BIGINT,
    candle_is_complete BOOLEAN,

    -- Legacy columns (TYPE_OF_PRICE_CLOSE, backward compatibility)
    bb_upper          DOUBLE PRECISION,
    bb_middle         DOUBLE PRECISION,
    bb_lower          DOUBLE PRECISION,
    ema_signal        DOUBLE PRECISION,
    sma_signal        DOUBLE PRECISION,
    rsi_signal        DOUBLE PRECISION,
    macd_value        DOUBLE PRECISION,
    macd_signal       DOUBLE PRECISION,

    -- TYPE_OF_PRICE_CLOSE
    close_bb_upper    DOUBLE PRECISION,
    close_bb_middle   DOUBLE PRECISION,
    close_bb_lower    DOUBLE PRECISION,
    close_ema_signal  DOUBLE PRECISION,
    close_rsi_signal  DOUBLE PRECISION,
    close_sma_signal  DOUBLE PRECISION,
    close_macd_value  DOUBLE PRECISION,
    close_macd_signal DOUBLE PRECISION,

    -- TYPE_OF_PRICE_OPEN
    open_bb_upper     DOUBLE PRECISION,
    open_bb_middle    DOUBLE PRECISION,
    open_bb_lower     DOUBLE PRECISION,
    open_ema_signal   DOUBLE PRECISION,
    open_rsi_signal   DOUBLE PRECISION,
    open_sma_signal   DOUBLE PRECISION,
    open_macd_value   DOUBLE PRECISION,
    open_macd_signal  DOUBLE PRECISION,

    -- TYPE_OF_PRICE_HIGH
    high_bb_upper     DOUBLE PRECISION,
    high_bb_middle    DOUBLE PRECISION,
    high_bb_lower     DOUBLE PRECISION,
    high_ema_signal   DOUBLE PRECISION,
    high_rsi_signal   DOUBLE PRECISION,
    high_sma_signal   DOUBLE PRECISION,
    high_macd_value   DOUBLE PRECISION,
    high_macd_signal  DOUBLE PRECISION,

    -- TYPE_OF_PRICE_LOW
    low_bb_upper      DOUBLE PRECISION,
    low_bb_middle     DOUBLE PRECISION,
    low_bb_lower      DOUBLE PRECISION,
    low_ema_signal    DOUBLE PRECISION,
    low_rsi_signal    DOUBLE PRECISION,
    low_sma_signal    DOUBLE PRECISION,
    low_macd_value    DOUBLE PRECISION,
    low_macd_signal   DOUBLE PRECISION,

    -- TYPE_OF_PRICE_AVG
    avg_bb_upper      DOUBLE PRECISION,
    avg_bb_middle     DOUBLE PRECISION,
    avg_bb_lower      DOUBLE PRECISION,
    avg_ema_signal    DOUBLE PRECISION,
    avg_rsi_signal    DOUBLE PRECISION,
    avg_sma_signal    DOUBLE PRECISION,
    avg_macd_value    DOUBLE PRECISION,
    avg_macd_signal   DOUBLE PRECISION,

    PRIMARY KEY (timestamp, figi)
);
CREATE INDEX IF NOT EXISTS ix_robot_market_data_timestamp
    ON robot_market_data (timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_robot_market_data_figi
    ON robot_market_data (figi);
"""

# Колонки в порядке, соответствующем $N плейсхолдерам
_INSERT_COLUMNS = [
    "timestamp", "figi",
    "candle_open", "candle_high", "candle_low", "candle_close",
    "candle_volume", "candle_is_complete",
    # legacy (close without prefix)
    "bb_upper", "bb_middle", "bb_lower",
    "ema_signal", "sma_signal", "rsi_signal",
    "macd_value", "macd_signal",
    # close
    "close_bb_upper", "close_bb_middle", "close_bb_lower",
    "close_ema_signal", "close_rsi_signal", "close_sma_signal",
    "close_macd_value", "close_macd_signal",
    # open
    "open_bb_upper", "open_bb_middle", "open_bb_lower",
    "open_ema_signal", "open_rsi_signal", "open_sma_signal",
    "open_macd_value", "open_macd_signal",
    # high
    "high_bb_upper", "high_bb_middle", "high_bb_lower",
    "high_ema_signal", "high_rsi_signal", "high_sma_signal",
    "high_macd_value", "high_macd_signal",
    # low
    "low_bb_upper", "low_bb_middle", "low_bb_lower",
    "low_ema_signal", "low_rsi_signal", "low_sma_signal",
    "low_macd_value", "low_macd_signal",
    # avg
    "avg_bb_upper", "avg_bb_middle", "avg_bb_lower",
    "avg_ema_signal", "avg_rsi_signal", "avg_sma_signal",
    "avg_macd_value", "avg_macd_signal",
]

_placeholders = ", ".join(f"${i}" for i in range(1, len(_INSERT_COLUMNS) + 1))
_columns_str = ", ".join(_INSERT_COLUMNS)

INSERT_SQL = f"""
INSERT INTO robot_market_data (
    {_columns_str}
) VALUES (
    {_placeholders}
)
ON CONFLICT (timestamp, figi) DO NOTHING
"""


async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Создаёт таблицу и индексы, если их нет (для standalone запуска)."""
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_DDL)


async def save_to_db(
    pool: asyncpg.Pool,
    snapshots: List[MarketSnapshot],
    figi: str,
) -> int:
    """Batch INSERT снимков в БД. Возвращает количество вставленных строк."""
    if not snapshots:
        return 0

    rows = [snapshot_to_db_row(s, figi=figi) for s in snapshots]
    values = [
        tuple(r[col] for col in _INSERT_COLUMNS)
        for r in rows
    ]

    async with pool.acquire() as conn:
        await conn.executemany(INSERT_SQL, values)

    logger.info("Saved %d rows to robot_market_data (figi=%s)", len(values), figi)
    return len(values)


async def main() -> None:
    """Точка входа: собирает датасет и сохраняет в PostgreSQL."""
    if not TOKEN:
        logger.error("TINVEST_TOKEN is not set. Set it in .env or environment.")
        return

    logger.info("Fetching dataset for figi=%s from %s to %s", FIGI, FROM_TS, TO_TS)
    snapshots = await build_ml_dataset(FIGI, FROM_TS, TO_TS)
    logger.info("Fetched %d snapshots", len(snapshots))

    if not snapshots:
        logger.warning("No data to save")
        return

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=4)
    try:
        await ensure_schema(pool)
        saved = await save_to_db(pool, snapshots, FIGI)
        logger.info("Done. Saved %d rows", saved)
    finally:
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
