"""Сервис рынка: бизнес-логика backend-frontend (Facade, паттерн python_test).

Отвечает за:
  * валидацию FIGI (только реально существующие в БД — требование безопасности);
  * сборку DTO MarketDataItem из сырых строк репозитория;
  * real-time конвейер: фоновый polling новых записей + рассылка подписчикам
    WebSocket по их FIGI (фильтрация на стороне сервера).

Группировка подписок «figi -> set(connections)» живёт здесь же: сервис —
единственный владелец состояния рассылок.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import WebSocket

from app.core.config import Settings
from app.repositories.market_repository import MarketRepository
from app.schemas.company import CompanyFigiItem
from app.schemas.market_data import MarketDataItem

logger = logging.getLogger(__name__)

# Максимум записей в initial-data (ТЗ: последние 500; не грузим фронт сверх меры).
INITIAL_DATA_LIMIT = 500

# Максимум записей в all-news (пагинация).
ALL_NEWS_LIMIT_MAX = 200


class MarketService:
    """Рыночные данные для Vue-фронта + real-time рассылка."""

    def __init__(self, settings: Settings, repository: MarketRepository) -> None:
        self._settings = settings
        self._repository = repository
        # figi -> множество активных WebSocket-подключений (фильтр на сервере)
        self._subscribers: dict[str, set[WebSocket]] = defaultdict(set)
        # figi -> (candle_time, ts) последней отправленной записи (курсор polling'а)
        self._cursor: dict[str, tuple[datetime | None, datetime | None]] = {}
        # Защита от гонок при изменении курсора/подписок
        self._lock = asyncio.Lock()
        self._poll_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    # --------------------------------- REST -----------------------------------
    async def list_figis(self) -> list[str]:
        """Уникальные FIGI, по которым есть данные в таблице."""
        return await self._repository.list_figis()

    async def list_companies(self) -> list[CompanyFigiItem]:
        """FIGI + название компании (LEFT JOIN company_profiles)."""
        rows = await self._repository.list_figis_with_names()
        return [CompanyFigiItem.model_validate(r) for r in rows]

    async def initial_data(self, figi: str) -> list[MarketDataItem] | None:
        """Последние 500 записей FIGI; None, если такого FIGI в БД нет (403/404 на роутере)."""
        if not await self._repository.figi_exists(figi):
            return None
        rows = await self._repository.recent_by_figi(figi, INITIAL_DATA_LIMIT)
        items = [MarketDataItem.model_validate(r) for r in rows]
        # Запоминаем курсор: polling отдаст только то, что новее последней истории.
        if items:
            last = items[-1]
            async with self._lock:
                self._cursor[figi] = (last.candle_time or last.ts, last.ts)
        return items

    async def news_by_id(self, news_id: UUID) -> MarketDataItem | None:
        row = await self._repository.news_by_id(news_id)
        return MarketDataItem.model_validate(row) if row else None

    async def figi_exists(self, figi: str) -> bool:
        """Публичный фасад валидации FIGI (используется и REST, и WS-роутером)."""
        return await self._repository.figi_exists(figi)

    async def all_news(self, limit: int, offset: int) -> tuple[list[MarketDataItem], int]:
        """Все записи из market_news_ml_dataset с пагинацией.

        Возвращает (список записей, общее количество).
        """
        safe_limit = min(limit, ALL_NEWS_LIMIT_MAX)
        safe_offset = max(offset, 0)
        rows = await self._repository.all_news(safe_limit, safe_offset)
        total = await self._repository.count_all()
        items = [MarketDataItem.model_validate(r) for r in rows]
        return items, total

    async def ping(self, figi: str) -> dict[str, int]:
        """Служебная in-band команда для интеграционных тестов real-time цикла.

        Ставит курсор polling'а на «сейчас» и возвращает число подписчиков FIGI —
        тест может детерминированно дождаться новых записей без ожидания истории.
        """
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        async with self._lock:
            self._cursor[figi] = (now, now)
            subs = len(self._subscribers.get(figi, ()))
        return {"figi": figi, "subscribers": subs}

    # ------------------------------ Подписки WS -------------------------------
    async def subscribe(self, websocket: WebSocket, figi: str) -> None:
        """Подписка соединения на FIGI; автоматическая отписка от предыдущего FIGI."""
        async with self._lock:
            # Отписка от прежнего FIGI этого же соединения (ТЗ п.4 протокола).
            for conns in self._subscribers.values():
                conns.discard(websocket)
            self._subscribers[figi].add(websocket)
            # Новый FIGI мог ещё не иметь курсора — поставим его по последней записи,
            # чтобы не слать клиенту историю, которую он уже получил по REST.
            if figi not in self._cursor:
                rows = await self._repository.recent_by_figi(figi, 1)
                if rows:
                    last = rows[-1]
                    self._cursor[figi] = (last.get("candle_time") or last.get("ts"), last.get("ts"))
                else:
                    self._cursor[figi] = (None, None)
        logger.info("WS подписка: figi=%s (всего соединений: %d)",
                    figi, sum(len(v) for v in self._subscribers.values()))

    def unsubscribe(self, websocket: WebSocket) -> None:
        """Убрать соединение из всех групп (закрытие WS)."""
        for conns in self._subscribers.values():
            conns.discard(websocket)

    @property
    def subscribed_figis(self) -> set[str]:
        return {figi for figi, conns in self._subscribers.items() if conns}

    # --------------------------- Real-time polling ----------------------------
    async def start(self) -> None:
        """Запуск фонового цикла рассылки (из lifespan, паттерн scheduler_worker)."""
        self._stop.clear()
        self._poll_task = asyncio.create_task(self._poll_loop(), name="market-poll-loop")
        logger.info("MarketService: цикл real-time запущен (interval=%.1fs)",
                    self._settings.ws_poll_interval_s)

    async def stop(self) -> None:
        """Корректная остановка: сначала отмена задачи, потом ничего не трогаем (порядок в lifespan)."""
        self._stop.set()
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        logger.info("MarketService: цикл real-time остановлен")

    async def _poll_loop(self) -> None:
        """Опрос БД по подписанным FIGI и отправка новых записей их подписчикам."""
        while not self._stop.is_set():
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — цикл живучий: ошибка логгируется
                logger.error("real-time polling: %s: %s", exc.__class__.__name__, exc)
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self._settings.ws_poll_interval_s
                )
            except asyncio.TimeoutError:
                pass

    async def _poll_once(self) -> None:
        figis = self.subscribed_figis
        if not figis:
            return
        for figi in sorted(figis):
            async with self._lock:
                since_time, since_ts = self._cursor.get(figi, (None, None))
            rows = await self._repository.new_since(figi, since_time, since_ts, limit=INITIAL_DATA_LIMIT)
            if not rows:
                continue
            items = [MarketDataItem.model_validate(r) for r in rows]
            # Сдвигаем курсор на самую свежую отправленную запись.
            last = items[-1]
            async with self._lock:
                self._cursor[figi] = (last.candle_time or last.ts, last.ts)
            await self._broadcast(figi, items)

    async def _broadcast(self, figi: str, items: list[MarketDataItem]) -> None:
        """Отправка новых записей ТОЛЬКО подписчикам этого FIGI (серверная фильтрация)."""
        conns = list(self._subscribers.get(figi, ()))
        dead: list[WebSocket] = []
        for item in items:
            payload = {
                "type": "new_data",
                "data": item.model_dump(mode="json"),
                "figi": figi,
            }
            for ws in conns:
                try:
                    await ws.send_json(payload)
                except Exception:  # noqa: BLE001 — соединение могло закрыться в полёте
                    if ws not in dead:
                        dead.append(ws)
        for ws in dead:
            self._subscribers.get(figi, set()).discard(ws)
        if items:
            logger.info("WS рассылка: figi=%s, %d записей, %d подписчиков",
                        figi, len(items), len(conns) - len(dead))

    # ------------------------------ Утилита -----------------------------------
    @staticmethod
    def to_dict(item: MarketDataItem) -> dict[str, Any]:
        """DTO -> JSON-ready dict (для send_json)."""
        return item.model_dump(mode="json")
