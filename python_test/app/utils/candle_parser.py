"""Парсинг свечей формата T-Invest API (структура ``units`` + ``nano``).

Конвертация денег в float выполняется строго по формуле из ТЗ:

    value = units + nano / 1_000_000_000

Дополнительно — нормализация времени (ISO 8601 с суффиксом ``Z``) и
вывод таймфрейма по медианному шагу между свечами.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Конвертация Money/Decimal (units + nano) → float
# ---------------------------------------------------------------------------


def money_to_float(money: dict | None) -> float | None:
    """Конвертирует объект ``{units, nano}`` из T-Invest API в float.

    Принимает как строковые, так и числовые значения полей.
    Возвращает ``None``, если поле отсутствует или имеет некорректный формат.
    """
    if money is None:
        return None
    if isinstance(money, (int, float)):  # уже число — принимаем как есть
        return float(money)
    if not isinstance(money, dict):
        return None
    try:
        units = int(str(money.get("units", 0)))
        nano = int(str(money.get("nano", 0)))
    except (TypeError, ValueError):
        return None
    return units + nano / 1_000_000_000


def parse_time(value: str | None) -> datetime | None:
    """Парсит ISO 8601-время T-Invest (``2026-11-01T18:25:00Z``) в aware-datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_float_or_none(value: Any) -> float | None:
    """Безопасная конвертация строкового числа (volume/volumeBuy/volumeSell) в float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def candles_to_dataframe(candles: list[dict[str, Any]]) -> Any:
    """Собирает плоский pandas.DataFrame из «сырых» свечей T-Invest API.

    Колонки: ``ts`` (datetime), ``timestamp`` (исходная строка), ``open``,
    ``high``, ``low``, ``close``, ``volume``, ``volume_buy``, ``volume_sell``,
    ``is_complete``, ``candle_source``. Свечи сортируются по времени
    (требование ТЗ: несоответствие порядка — авто-сортировка).
    """
    import pandas as pd

    rows: list[dict[str, Any]] = []
    for candle in candles:
        ts = parse_time(candle.get("time"))
        o = money_to_float(candle.get("open"))
        h = money_to_float(candle.get("high"))
        lo = money_to_float(candle.get("low"))
        c = money_to_float(candle.get("close"))
        if ts is None or o is None or h is None or lo is None or c is None:
            continue  # неполная/битая свеча — пропускаем (логирование — на уровне сервиса)
        rows.append(
            {
                "ts": ts,
                "timestamp": candle.get("time"),
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": to_float_or_none(candle.get("volume")) or 0.0,
                "volume_buy": to_float_or_none(candle.get("volumeBuy")) or 0.0,
                "volume_sell": to_float_or_none(candle.get("volumeSell")) or 0.0,
                "is_complete": bool(candle.get("isComplete", True)),
                "candle_source": candle.get("candleSource"),
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("ts").reset_index(drop=True)
    return df


def infer_timeframe_minutes(df: Any) -> int:
    """Определяет таймфрейм (в минутах) по медианному шагу между свечами.

    Медиана устойчива к гэпам выходных/ночных перерывов рынка MOEX.
    """
    if df is None or df.empty or len(df) < 2:
        return 5  # значение по умолчанию (М5)
    deltas = df["ts"].diff().dropna()
    if deltas.empty:
        return 5
    median_seconds = statistics.median(deltas.dt.total_seconds().tolist())
    minutes = max(1, round(median_seconds / 60))
    return minutes


def find_time_gaps(df: Any, timeframe_minutes: int) -> list[int]:
    """Возвращает индексы строк, где шаг между свечами больше таймфрейма.

    Используется для логирования warning'ов (ТЗ п.3.4: пропуски во времени —
    предупреждаем, но считаем дальше). Ночные/выходные разрывы — штатная
    ситуация для биржевых данных, поэтому это именно warning, а не ошибка.
    """
    if df is None or df.empty or len(df) < 2:
        return []
    expected = timeframe_minutes * 60
    deltas = df["ts"].diff().dt.total_seconds()
    return [int(i) for i in range(1, len(df)) if deltas.iloc[i] > expected * 1.5]
