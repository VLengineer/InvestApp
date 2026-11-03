"""Репозиторий таблицы ``market_news_ml_dataset``: единственный модуль, знающий SQL.

Паттерн scheduler_service/app/db/repository.py и python_test/app/repositories:
тонкая обёртка над живым asyncpg-пулом, SQL-константы сверху модуля,
полная параметризация (никакой интерполяции пользовательских строк).

backend-frontend только читает: пишет в таблицу n8n-workflow напрямую.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)

# Колонки строки датасета (порядок = models/market_news_ml_dataset.ALL_COLUMNS).
_DATA_COLUMNS = """
    id, figi, source, title, content, ts, candle_time,
    open_price, high_price, low_price, close_price,
    volume, volume_buy, volume_sell, is_complete,
    rsi_14, stoch_k, stoch_d, cci_20, williams_r, roc_12, mfi_14,
    macd, macd_signal, adx_14, atr_14,
    limit_up_units, limit_down_units, close_price_units, last_price_units, price_currency,
    last_price_ts, orderbook_ts, close_price_ts, depth,
    ai_sentiment_score, ai_relevance_score, ai_expected_impact, ai_confidence,
    ai_text_summary, ai_raw_response,
    target_horizon_minutes, target_future_return_pct, target_direction,
    target_volatility_threshold_pct
"""

# ---------------------------------- FIGI ------------------------------------
# Уникальные FIGI, по которым реально есть данные (валидация селектора на фронте).
_LIST_FIGIS_SQL = """
    SELECT DISTINCT figi
    FROM market_news_ml_dataset
    WHERE figi IS NOT NULL AND figi <> ''
    ORDER BY figi
"""

_FIGI_EXISTS_SQL = "SELECT 1 FROM market_news_ml_dataset WHERE figi = $1 LIMIT 1"

# ------------------------------ История по FIGI -------------------------------
# Последние N записей для конкретного FIGI; наружу отдаём в хронологическом
# порядке (графикам слева направо), берём хвост через подзапрос DESC/LIMIT.
_SELECT_RECENT_BY_FIGI_SQL = f"""
    SELECT * FROM (
        SELECT {_DATA_COLUMNS}
        FROM market_news_ml_dataset
        WHERE figi = $1
        ORDER BY COALESCE(candle_time, ts) DESC NULLS LAST, ts DESC NULLS LAST
        LIMIT $2
    ) recent
    ORDER BY COALESCE(candle_time, ts) ASC NULLS LAST, ts ASC NULLS LAST
"""

# --------------------------------- Новости ----------------------------------
_SELECT_NEWS_BY_ID_SQL = f"SELECT {_DATA_COLUMNS} FROM market_news_ml_dataset WHERE id = $1"

# --------------------------- Стакан (orderbook) -------------------------------
# ONE-to-many: заявки двух таблиц одной записью-«пакетом» (экономим round-trip).
_SELECT_ORDERBOOK_FOR_IDS_SQL = """
    SELECT 'ask' AS side, market_data_id, position, price_units, price_nano, quantity
    FROM orderbook_asks WHERE market_data_id = ANY($1::uuid[])
    UNION ALL
    SELECT 'bid' AS side, market_data_id, position, price_units, price_nano, quantity
    FROM orderbook_bids WHERE market_data_id = ANY($1::uuid[])
    ORDER BY market_data_id, side, position
"""

# ----------------------- Новые записи (real-time polling) ----------------------
# Инкрементальная выборка строго после последней известной свечи/времени.
# Ключ сравнения — кортеж (candle_time, ts): исключает пропуск записей
# с одинаковым временем на границе батча.
_SELECT_NEW_SINCE_SQL = f"""
    SELECT {_DATA_COLUMNS}
    FROM market_news_ml_dataset
    WHERE figi = $1
      AND (COALESCE(candle_time, ts), COALESCE(ts, 'epoch'::timestamptz)) > ($2, $3)
    ORDER BY COALESCE(candle_time, ts) ASC NULLS LAST, ts ASC NULLS LAST
    LIMIT $4
"""


def _row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    """asyncpg.Record -> dict; JSONB может прийти строкой — приводим к dict (паттерн python_test)."""
    data = dict(row)
    raw = data.get("ai_raw_response")
    if isinstance(raw, (str, bytes)):
        try:
            data["ai_raw_response"] = json.loads(raw)
        except ValueError:
            data["ai_raw_response"] = None
    return data


class MarketRepository:
    """Чтение market_news_ml_dataset + стакана."""

    def __init__(self, pool_provider: Any) -> None:
        # pool_provider — объект с атрибутом .pool (app.db.database.Database):
        # ссылка на пул берётся в момент вызова, а не при сборке контейнера.
        self._pool_provider = pool_provider

    @property
    def _pool(self) -> asyncpg.Pool:
        return self._pool_provider.pool  # type: ignore[union-attr,no-any-return]

    # ------------------------------------------------------------------ FIGI --
    async def list_figis(self) -> list[str]:
        rows = await self._pool.fetch(_LIST_FIGIS_SQL)
        figis = [r["figi"] for r in rows]
        logger.info("PostgreSQL <<< list_figis: %d шт", len(figis))
        return figis

    async def figi_exists(self, figi: str) -> bool:
        """Валидация FIGI: есть ли такие данные в БД вообще (безопасность фронта)."""
        row = await self._pool.fetchval(_FIGI_EXISTS_SQL, figi)
        return row is not None

    # -------------------------------------------------------------- История ---
    async def recent_by_figi(self, figi: str, limit: int) -> list[dict[str, Any]]:
        rows = await self._pool.fetch(_SELECT_RECENT_BY_FIGI_SQL, figi, limit)
        logger.info("PostgreSQL <<< recent_by_figi(%s, limit=%d): %d строк", figi, limit, len(rows))
        records = [_row_to_dict(r) for r in rows]
        await self._attach_orderbook(records)
        return records

    # --------------------------------------------------------------- Новости --
    async def news_by_id(self, news_id: UUID) -> dict[str, Any] | None:
        row = await self._pool.fetchrow(_SELECT_NEWS_BY_ID_SQL, news_id)
        if row is None:
            return None
        record = _row_to_dict(row)
        await self._attach_orderbook([record])
        return record

    # ----------------------------------------------------- Инкрементальная ----
    async def new_since(
        self,
        figi: str,
        since_time: datetime | None,
        since_ts: datetime | None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Новые записи FIGI строго после (since_time, since_ts)."""
        epoch = datetime.fromtimestamp(0, tz=timezone.utc)
        rows = await self._pool.fetch(
            _SELECT_NEW_SINCE_SQL, figi, since_time or epoch, since_ts or epoch, limit
        )
        records = [_row_to_dict(r) for r in rows]
        if records:
            logger.info("PostgreSQL <<< new_since(%s): %d новых", figi, len(records))
        await self._attach_orderbook(records)
        return records

    # ---------------------------------------------------------------- Стакан --
    async def _attach_orderbook(self, records: list[dict[str, Any]]) -> None:
        """Добавляет в каждую запись списки заявок asks/bids (одним запросом на пакет)."""
        if not records:
            return
        ids = [r["id"] for r in records]
        rows = await self._pool.fetch(_SELECT_ORDERBOOK_FOR_IDS_SQL, ids)
        by_id: dict[UUID, dict[str, list[dict[str, Any]]]] = {
            rid: {"asks": [], "bids": []} for rid in ids
        }
        for row in rows:
            level = {
                "position": row["position"],
                # MoneyValue: value = units + nano / 1e9 (формула конверсии проекта)
                "price": float(row["price_units"]) + float(row["price_nano"]) / 1e9,
                "quantity": float(row["quantity"]),
            }
            by_id[row["market_data_id"]]["asks" if row["side"] == "ask" else "bids"].append(level)
        for rec in records:
            rec["orderbook_asks"] = by_id[rec["id"]]["asks"]
            rec["orderbook_bids"] = by_id[rec["id"]]["bids"]
