"""Интеграционные тесты backend-frontend с ФЕЙКОВОЙ БД (без PostgreSQL).

Реальный asyncpg-пул подменяется FakePool с тем же интерфейсом
(fetch/fetchrow/fetchval), что позволяет проверить:
  * REST-эндпоинты (/api/market/*) и валидацию FIGI/UUID;
  * WS-протокол подписки и серверную фильтрацию по FIGI;
  * фоновый цикл рассылки (polling -> new_data).
SQL в фейке не исполняется — эмулируются только нужные запросам формы строк.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest


def make_row(figi: str = "BBG000B9XRY4", ts_offset_s: int = 0, with_ai: bool = True) -> dict:
    """Одна «строка» market_news_ml_dataset в формате, который возвращает fake fetch."""
    base = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
    t = datetime.fromtimestamp(base.timestamp() + ts_offset_s, tz=timezone.utc)
    return {
        "id": uuid4(),
        "figi": figi,
        "source": "TestSource",
        "title": f"Тестовая новость {ts_offset_s}",
        "content": "Текст новости",
        "ts": t,
        "candle_time": t,
        "open_price": 100.0, "high_price": 105.0, "low_price": 99.0, "close_price": 103.0,
        "volume": 1000, "volume_buy": 600, "volume_sell": 400, "is_complete": True,
        "rsi_14": 55.0, "stoch_k": 60.0, "stoch_d": 58.0, "cci_20": 12.0,
        "williams_r": -40.0, "roc_12": 1.5, "mfi_14": 52.0,
        "macd": 0.25, "macd_signal": 0.2, "adx_14": 22.0, "atr_14": 1.1,
        "limit_up_units": 120.0, "limit_down_units": 80.0,
        "close_price_units": 103.0, "last_price_units": 103.5,
        "price_currency": "RUB",
        "last_price_ts": t, "orderbook_ts": t, "close_price_ts": t,
        "depth": 10,
        "ai_sentiment_score": 0.4 if with_ai else None,
        "ai_relevance_score": 0.8 if with_ai else None,
        "ai_expected_impact": 1.2 if with_ai else None,
        "ai_confidence": 0.7 if with_ai else None,
        "ai_text_summary": "ИИ саммари" if with_ai else None,
        "ai_raw_response": {"model": "fake"} if with_ai else None,
        "target_horizon_minutes": 60,
        "target_future_return_pct": 0.5, "target_direction": 1,
        "target_volatility_threshold_pct": 1.0,
    }


class FakePool:
    """Мини-эмуляция asyncpg.Pool: распознаёт SQL репозитория по ключевым фразам."""

    def __init__(self) -> None:
        self.rows: list[dict] = []          # «таблица» датасета
        self.orderbook: list[dict] = []     # «таблица» стакана (side ask/bid)

    # -- интерфейс пула ------------------------------------------------------
    async def fetch(self, sql: str, *args):
        s = re.sub(r"\s+", " ", sql)
        if "DISTINCT figi" in s:
            figis = sorted({r["figi"] for r in self.rows if r["figi"]})
            return [{"figi": f} for f in figis]
        if "FROM orderbook_asks" in s and "UNION ALL" in s:
            ids = set(args[0])
            return [o for o in self.orderbook if o["market_data_id"] in ids]
        if "new_since" in s or "(COALESCE(candle_time, ts), COALESCE(ts" in s:
            figi, since_time, since_ts, limit = args
            out = [
                r for r in self.rows
                if r["figi"] == figi
                and (r["candle_time"], r["ts"]) > (since_time, since_ts)
            ]
            return sorted(out, key=lambda r: (r["candle_time"], r["ts"]))[:limit]
        if "recent_by_figi" in s or ("WHERE figi = $1" in s and "LIMIT $2" in s):
            figi, limit = args
            out = sorted((r for r in self.rows if r["figi"] == figi),
                         key=lambda r: (r["candle_time"], r["ts"]), reverse=True)[:limit]
            return list(reversed(out))
        raise AssertionError(f"FakePool: неизвестный SELECT: {s[:120]}")

    async def fetchrow(self, sql: str, *args):
        s = re.sub(r"\s+", " ", sql)
        if "to_regclass" in s:
            return {"dataset": "market_news_ml_dataset", "asks": "orderbook_asks", "bids": "orderbook_bids"}
        if "SELECT 1 AS ok" in s:
            return {"ok": 1}
        if "WHERE id = $1" in s:
            rows = [r for r in self.rows if r["id"] == args[0]]
            return rows[0] if rows else None
        raise AssertionError(f"FakePool: неизвестный fetchrow: {s[:120]}")

    async def fetchval(self, sql: str, *args):
        s = re.sub(r"\s+", " ", sql)
        if "WHERE figi = $1 LIMIT 1" in s:
            return 1 if any(r["figi"] == args[0] for r in self.rows) else None
        raise AssertionError(f"FakePool: неизвестный fetchval: {s[:120]}")

    async def execute(self, sql: str):  # pragma: no cover - не используется
        return None

    async def close(self) -> None:
        return None


@pytest.fixture()
def fake_pool() -> FakePool:
    return FakePool()
