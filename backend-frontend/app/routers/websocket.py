"""WebSocket real-time: WS /ws/market-updates.

Протокол (ТЗ):
  1. клиент подключается;
  2. шлёт {"type": "subscribe", "figi": "..."};
  3. сервер шлёт только НОВЫЕ записи этого FIGI:
     {"type": "new_data", "data": MarketDataItem, "figi": "..."};
  4. при смене FIGI — новая подписка (сервер сам отписывает от прежнего);
  5. фильтрация по FIGI — на стороне сервера.

Дополнительные служебные сообщения сервера: subscribe_ack / error.
Служебные команды клиента: {"type":"unsubscribe"}, {"type":"ping","figi":...}
(для интеграционных тестов рассылки).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

router = APIRouter()


class SubscribeMessage(BaseModel):
    """Валидация входящего сообщения подписки."""

    type: str = Field(pattern="^subscribe$")
    figi: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")


@router.websocket("/ws/market-updates")
async def market_updates(websocket: WebSocket) -> None:
    """Единая real-time точка для всех клиентов дашборда."""
    # Зависимость из app.state достаем вручную (state собирается в lifespan).
    market = getattr(websocket.app.state, "market_service", None)
    if market is None:
        await websocket.close(code=1013, reason="Сервис рынка ещё не готов")
        return

    await websocket.accept()
    subscribed_figi: str | None = None
    logger.info("WS /ws/market-updates: подключение (%s)",
                websocket.client.host if websocket.client else "?")
    try:
        while True:
            message: Any = await websocket.receive_json()
            mtype = message.get("type") if isinstance(message, dict) else None

            # Служебные команды (не из ТЗ-протокола, нужны для тестов/гигиены).
            if mtype == "unsubscribe":
                market.unsubscribe(websocket)
                subscribed_figi = None
                await websocket.send_json({"type": "unsubscribe_ack"})
                continue
            if mtype == "ping":
                info = await market.ping(str(message.get("figi", "")))
                await websocket.send_json({"type": "pong", **info})
                continue

            try:
                sub = SubscribeMessage.model_validate(message)
            except ValidationError as exc:
                await websocket.send_json({
                    "type": "error",
                    "message": 'Ожидается {"type": "subscribe", "figi": "..."}',
                    "details": exc.errors(include_url=False, include_input=False),
                })
                continue

            # Валидация FIGI по БД: не подписываем на несуществующий инструмент.
            if not await market.figi_exists(sub.figi):
                await websocket.send_json({
                    "type": "error",
                    "message": f"FIGI {sub.figi} не найден среди данных в БД",
                    "figi": sub.figi,
                })
                continue

            await market.subscribe(websocket, sub.figi)
            subscribed_figi = sub.figi
            await websocket.send_json({"type": "subscribe_ack", "figi": sub.figi})
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 — битый JSON/сеть: закрываем соединение
        logger.warning("WS /ws/market-updates: ошибка соединения (%s): %s", subscribed_figi, exc)
    finally:
        market.unsubscribe(websocket)
        logger.info("WS /ws/market-updates: отключение (figi=%s)", subscribed_figi)
