"""Тесты REST + WebSocket backend-frontend (фейковый пул вместо PostgreSQL)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend-frontend/

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.database import Database
from app.main import app
from app.repositories.market_repository import MarketRepository
from app.services.market_service import MarketService
from conftest import FakePool, make_row

FIGI_A = "BBG000B9XRY4"   # Gazprom
FIGI_B = "BBG004730N88"   # Sberbank


@pytest.fixture()
def pool() -> FakePool:
    p = FakePool()
    # История: 3 записи FIGI_A (последняя с ИИ-аналитикой), 2 записи FIGI_B.
    for i in range(3):
        p.rows.append(make_row(FIGI_A, ts_offset_s=i * 300, with_ai=(i == 2)))
    for i in range(2):
        p.rows.append(make_row(FIGI_B, ts_offset_s=i * 300))
    # Стакан для первой записи A.
    first_a = p.rows[0]
    p.orderbook.append({"side": "ask", "market_data_id": first_a["id"], "position": 1,
                        "price_units": 104, "price_nano": 500000000, "quantity": 10})
    p.orderbook.append({"side": "bid", "market_data_id": first_a["id"], "position": 1,
                        "price_units": 103, "price_nano": 0, "quantity": 5})
    return p


@pytest.fixture()
def client(pool: FakePool):
    """Собираем приложение поверх фейкового пула (без реального lifespan к БД)."""
    settings = get_settings()
    database = Database(settings)
    database._pool = pool  # подмена пула
    repository = MarketRepository(database)
    service = MarketService(settings, repository)
    # polling с крошечным интервалом — тест рассылки не ждёт 5 секунд
    service._settings = type("S", (), {"ws_poll_interval_s": 0.2})()
    app.state.database = database
    app.state.market_service = service

    # Патчим Database.connect/close в lifespan: пул уже «живой» фейк.
    async def _noop_connect(self): self._pool = pool
    async def _noop_close(self): self._pool = None
    Database.connect = _noop_connect  # type: ignore[method-assign]
    Database.close = _noop_close  # type: ignore[method-assign]

    with TestClient(app) as c:
        yield c

    # Останавливаем фоновый цикл, созданный lifespan (TestClient сам зовёт shutdown).
    del app.state.market_service


def test_live_ready(client):
    assert client.get("/live").json()["status"] == "ok"
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ok"


def test_figis(client):
    body = client.get("/api/market/figis").json()
    assert sorted(body["figis"]) == sorted([FIGI_A, FIGI_B])


def test_initial_data_order_and_limit(client):
    r = client.get("/api/market/initial-data", params={"figi": FIGI_A})
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 3
    # Хронологический порядок (старые -> новые)
    times = [d["candle_time"] for d in data]
    assert times == sorted(times)
    item = data[-1]
    assert item["figi"] == FIGI_A
    assert item["ai_text_summary"] == "ИИ саммари"
    # Стакан прикреплён только к первой записи
    assert data[0]["orderbook_asks"][0]["price"] == pytest.approx(104.5)
    assert data[0]["orderbook_bids"][0]["quantity"] == 5


def test_initial_data_unknown_figi_404(client):
    assert client.get("/api/market/initial-data", params={"figi": "NOPE123"}).status_code == 404


def test_initial_data_bad_figi_format_422(client):
    assert client.get("/api/market/initial-data", params={"figi": "bad figi!"}).status_code == 422


def test_news_by_id(client):
    target = next(r for r in client.app.state.pool_rows if False) if False else None  # noqa
    # Берём id из initial-data
    data = client.get("/api/market/initial-data", params={"figi": FIGI_A}).json()["data"]
    news_id = data[-1]["id"]
    r = client.get(f"/api/market/news/{news_id}")
    assert r.status_code == 200
    news = r.json()["news"]
    assert news["id"] == news_id
    assert news["title"].startswith("Тестовая новость")
    assert news["ai_sentiment_score"] == 0.4


def test_news_bad_uuid_422(client):
    assert client.get("/api/market/news/not-a-uuid").status_code == 422


def test_news_unknown_404(client):
    from uuid import uuid4
    assert client.get(f"/api/market/news/{uuid4()}").status_code == 404


def test_ws_subscribe_and_filtering(client):
    """Клиент подписан на FIGI_A и НЕ получает данные FIGI_B (серверная фильтрация)."""
    with client.websocket_connect("/ws/market-updates") as ws:
        ws.send_json({"type": "subscribe", "figi": FIGI_A})
        ack = ws.receive_json()
        assert ack == {"type": "subscribe_ack", "figi": FIGI_A}

        # Проверяем состояние сервера: подписчик числится только за FIGI_A
        service: MarketService = app.state.market_service
        assert service.subscribed_figis == {FIGI_A}

        # Курсор после subscribe стоит на последней истории; добавляем НОВУЮ запись A
        # и новую запись B — клиент должен увидеть только A.
        new_a = make_row(FIGI_A, ts_offset_s=10_000_000)
        new_b = make_row(FIGI_B, ts_offset_s=10_000_000)
        service._repository._pool_provider._pool.rows.extend([new_a, new_b])  # noqa: SLF001

        msg = ws.receive_json()  # ждём рассылку (poll interval 0.2s)
        assert msg["type"] == "new_data"
        assert msg["figi"] == FIGI_A
        assert msg["data"]["id"] == str(new_a["id"])

        # Смена подписки на B: старая отменяется автоматически
        ws.send_json({"type": "subscribe", "figi": FIGI_B})
        assert ws.receive_json()["figi"] == FIGI_B
        assert service.subscribed_figis == {FIGI_B}

        # Битое сообщение -> error без разрыва соединения
        ws.send_json({"type": "nonsense"})
        err = ws.receive_json()
        assert err["type"] == "error"

        # Несуществующий FIGI -> error
        ws.send_json({"type": "subscribe", "figi": "ZZZZZZZZZZ"})
        err2 = ws.receive_json()
        assert err2["type"] == "error" and "не найден" in err2["message"]
