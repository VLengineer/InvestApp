"""Тесты POST /indicators/calculate: индикаторы + аналитика + обработка ошибок.

Приложение собирается минимальным (только api_router + обработчик AppError, как в
app/main.py) — БД/Ollama не требуются, тесты работают без внешних сервисов.
JWT-токен генерируется тестовым секретом (переопределение get_settings).
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.routes import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError

SECRET = "test-secret-key-0123456789abcdef-0123456789abcdef"


# ---------------------------------------------------------------------------
# Мини-приложение (без Container/БД) — так же, как делает test_run_endpoint.py
# ---------------------------------------------------------------------------
def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(api_router)

    @app.exception_handler(AppError)
    async def _app_error(_request, exc: AppError) -> JSONResponse:  # копия поведения main.py
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, "details": exc.details},
        )

    settings = Settings(
        _env_file=None,
        jwt_secret_key=SECRET,
        postgres_user="u",
        postgres_password="p",
        environment="test",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(_build_app())


@pytest.fixture(scope="module")
def auth() -> dict[str, str]:
    token = pyjwt.encode(
        {"sub": "pytest", "iat": datetime.now(timezone.utc)}, SECRET, algorithm="HS256"
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Генерация свечей в формате T-Invest API (units/nano)
# ---------------------------------------------------------------------------
def _money(value: float) -> dict:
    units = int(value)
    nano = round((value - units) * 1_000_000_000)
    return {"units": str(units), "nano": nano}


def make_candle(
    ts: datetime, o: float, h: float, l: float, c: float,
    volume: int = 1000, buy: int | None = None, sell: int | None = None,
    complete: bool = True,
) -> dict:
    return {
        "open": _money(o), "high": _money(h), "low": _money(l), "close": _money(c),
        "volume": str(volume),
        "time": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "isComplete": complete,
        "candleSource": "CANDLE_SOURCE_TINVEST_INDICATIVE",
        "volumeBuy": str(buy if buy is not None else volume // 2),
        "volumeSell": str(sell if sell is not None else volume // 2),
    }


def make_flat_candles(n: int = 60, start_price: float = 296.79) -> list[dict]:
    """Ровный ряд без паттернов: open == close, минимальные тени, стабильный объём."""
    t0 = datetime(2026, 11, 1, 18, 25, tzinfo=timezone.utc)
    candles = []
    for i in range(n):
        p = start_price + 0.001 * (i % 3)  # микро-флуктуации, выраженного тренда нет
        candles.append(make_candle(t0 + timedelta(minutes=5 * i), p, p + 0.01, p - 0.01, p))
    return candles


def make_rich_candles() -> list[dict]:
    """Набор с гарантированными событиями аналитики (тренд, гэп, объём, паттерны).

    Структура (таймфрейм 5 минут):
      * свечи 0..41   — ровная база (warmup);
      * 10 растущих свечей подряд → тренд up;
      * гэп вверх > 0.05% + spike объёма (> 3×SMA20, volumeBuy > volumeSell);
      * медвежье поглощение, молот, перевёрнутый молот, доджи.
    """
    t0 = datetime(2026, 11, 1, 18, 25, tzinfo=timezone.utc)
    candles: list[dict] = []

    def add(idx: int, o: float, h: float, l: float, c: float, **kw) -> None:
        candles.append(make_candle(t0 + timedelta(minutes=5 * idx), o, h, l, c, **kw))

    base = 296.7
    # 0..41 — ровная база (open==close, симметричные тени, объём 1000)
    for i in range(42):
        add(i, base, base + 0.05, base - 0.05, base)

    # 42..51 — затяжной рост: каждый close выше предыдущего (тренд из 10+ свечей)
    price = base
    for k in range(10):
        prev_close = price
        price = prev_close + 0.02
        add(42 + k, prev_close, price + 0.005, prev_close - 0.005, price)

    # 52 — гэп вверх (open заметно выше prev close) + spike объёма (buy-dominant)
    gap_open = price + 0.30
    add(52, gap_open, gap_open + 0.05, price + 0.01, gap_open + 0.02, volume=30375,
        buy=20000, sell=10375)

    # 53 — медвежье поглощение: предыдущая (52) бычья, текущая медвежья перекрывает тело
    add(53, gap_open + 0.04, gap_open + 0.06, gap_open - 0.60, gap_open - 0.50)

    # 54 — ровная свеча-фон для паттернов
    flat = gap_open - 0.50
    add(54, flat, flat + 0.05, flat - 0.05, flat)

    # 55 — молот: длинная нижняя тень, маленькое тело сверху
    add(55, flat - 0.05, flat, flat - 0.60, flat - 0.10)

    # 56 — перевёрнутый молот: длинная верхняя тень, маленькое тело снизу
    add(56, flat - 0.10, flat + 0.60, flat - 0.15, flat - 0.05)

    # 57 — доджи: тело ≈ 0 при широком диапазоне
    add(57, flat - 0.05, flat + 0.30, flat - 0.35, flat - 0.052)

    # 58..70 — хвост ровных свечей (ATR/momentum по последним свечам стабилен)
    for i in range(58, 71):
        add(i, flat, flat + 0.05, flat - 0.05, flat)

    return candles


# ---------------------------------------------------------------------------
# Тест 1: индикаторы (критерии 1–3, 5)
# ---------------------------------------------------------------------------
def test_indicators_calculate_full_response(client: TestClient, auth: dict) -> None:
    body = {"candles": make_flat_candles(60)}
    resp = client.post("/indicators/calculate", json=body, headers=auth)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # структура ответа (ТЗ 2.1 + поле last_candle_rsi)
    assert set(data) == {"indicators", "analytics", "metadata", "last_candle_rsi"}
    assert set(data["analytics"]) == {
        "gaps", "volume_anomalies", "trends", "candle_patterns",
        "volatility_regime", "momentum",
    }

    indicators = data["indicators"]
    assert len(indicators) == 60
    expected_fields = {
        "timestamp", "rsi_14", "stoch_k", "stoch_d", "macd", "macd_signal",
        "cci_20", "williams_r", "mfi_14", "adx_14", "roc_12", "atr_14", "is_valid",
    }
    assert set(indicators[0]) == expected_fields

    # warmup: первые 40 — is_valid=false, остальные — true (критерий 3)
    assert all(row["is_valid"] is False for row in indicators[:40])
    assert all(row["is_valid"] is True for row in indicators[40:])

    # последняя свеча: все 9 индикаторов рассчитаны и в разумных границах
    last = indicators[-1]
    assert 0.0 <= last["rsi_14"] <= 100.0

    # RSI последней свечи продублирован в верхнеуровневом поле last_candle_rsi
    lcr = data["last_candle_rsi"]
    assert set(lcr) == {"timestamp", "rsi_14"}
    assert lcr["timestamp"] == last["timestamp"]
    assert lcr["rsi_14"] == last["rsi_14"]
    assert 0.0 <= last["stoch_k"] <= 100.0
    assert 0.0 <= last["stoch_d"] <= 100.0
    assert last["macd"] is not None and last["macd_signal"] is not None
    assert last["cci_20"] is not None and abs(last["cci_20"]) < 1000  # sanity: без бага pandas-ta
    assert -100.0 <= last["williams_r"] <= 0.0
    assert 0.0 <= last["mfi_14"] <= 100.0
    assert 0.0 <= last["adx_14"] <= 100.0
    assert last["roc_12"] is not None
    assert last["atr_14"] is not None and last["atr_14"] >= 0.0

    # метаданные
    meta = data["metadata"]
    assert meta["total_candles"] == 60
    assert meta["valid_candles"] == 20
    assert meta["warmup_period"] == 40
    assert meta["timeframe_minutes"] == 5
    assert isinstance(meta["calculation_time_ms"], int)


# ---------------------------------------------------------------------------
# Тест 2: аналитика (критерий 4)
# ---------------------------------------------------------------------------
def test_analytics_detects_all_event_types(client: TestClient, auth: dict) -> None:
    body = {"candles": make_rich_candles()}
    resp = client.post("/indicators/calculate", json=body, headers=auth)
    assert resp.status_code == 200, resp.text
    analytics = resp.json()["analytics"]

    # --- гэпы (2.3.1) ---
    gaps = analytics["gaps"]
    assert gaps, "Ожидался гэп вверх после серии роста"
    gap = gaps[0]
    assert set(gap) == {"timestamp", "gap_percent", "direction", "severity"}
    assert gap["direction"] == "up"
    assert gap["gap_percent"] > 0.05  # порог ТЗ
    assert gap["severity"] in {"low", "medium", "high"}

    # --- аномалии объёма (2.3.2) ---
    anomalies = analytics["volume_anomalies"]
    assert anomalies, "Ожидался spike объёма 30375 > 3×SMA20"
    anomaly = anomalies[0]
    assert set(anomaly) == {
        "timestamp", "volume", "avg_volume_20", "anomaly_ratio", "direction",
    }
    assert anomaly["volume"] == 30375
    assert anomaly["anomaly_ratio"] > 3.0
    assert anomaly["direction"] == "buy"  # volumeBuy(20000) > volumeSell(10375)

    # --- тренды (2.3.3) ---
    trends = analytics["trends"]
    assert trends, "Ожидался восходящий тренд 5+ свечей"
    trend = max(trends, key=lambda t: t["duration_candles"])
    assert set(trend) == {
        "start_timestamp", "end_timestamp", "duration_candles",
        "price_change_percent", "direction", "strength",
    }
    assert trend["direction"] == "up"
    assert trend["duration_candles"] >= 5
    assert trend["price_change_percent"] > 0
    assert trend["strength"] in {"weak", "medium", "strong"}

    # --- свечные паттерны (2.3.4) ---
    patterns = {p["pattern"] for p in analytics["candle_patterns"]}
    for expected in {"bearish_engulfing", "hammer", "inverted_hammer", "doji"}:
        assert expected in patterns, f"Паттерн {expected} не обнаружен: {patterns}"
    for p in analytics["candle_patterns"]:
        assert set(p) == {"timestamp", "pattern", "confidence"}
        assert 0.0 <= p["confidence"] <= 1.0

    # --- режим волатильности (2.3.5) ---
    vol = analytics["volatility_regime"]
    assert set(vol) == {"current_atr", "avg_atr_20", "regime", "ratio"}
    assert vol["regime"] in {"low_volatility", "normal", "high_volatility"}
    assert vol["current_atr"] is not None and vol["avg_atr_20"] is not None
    if vol["ratio"] is not None:
        assert vol["ratio"] > 0

    # --- моментум (2.3.6) ---
    mom = analytics["momentum"]
    assert set(mom) == {"current", "acceleration", "regime"}
    assert mom["regime"] in {
        "bullish_acceleration", "bullish_deceleration",
        "bearish_acceleration", "bearish_deceleration", "neutral",
    }


# ---------------------------------------------------------------------------
# Тест 3: ошибки и edge-cases (ТЗ 3.4)
# ---------------------------------------------------------------------------
def test_too_few_candles_returns_400(client: TestClient, auth: dict) -> None:
    body = {"candles": make_flat_candles(39)}
    resp = client.post("/indicators/calculate", json=body, headers=auth)
    assert resp.status_code == 400
    payload = resp.json()
    assert payload["message"] == "Минимум 40 свечей для расчета индикаторов"
    assert payload["code"] == "not_enough_candles"


def test_unauthenticated_returns_401(client: TestClient) -> None:
    resp = client.post("/indicators/calculate", json={"candles": make_flat_candles(45)})
    assert resp.status_code == 401


def test_unsorted_candles_are_sorted_automatically(client: TestClient, auth: dict) -> None:
    candles = make_flat_candles(50)
    shuffled = copy.deepcopy(candles)
    shuffled.reverse()  # заведомо несоортированный вход
    resp = client.post("/indicators/calculate", json={"candles": shuffled}, headers=auth)
    assert resp.status_code == 200, resp.text
    timestamps = [row["timestamp"] for row in resp.json()["indicators"]]
    assert timestamps == sorted(timestamps)
    # исходный порядок восстановлен → значения совпадают с отсортированным запросом
    resp2 = client.post("/indicators/calculate", json={"candles": candles}, headers=auth)
    assert resp2.json()["indicators"] == resp.json()["indicators"]


def test_incomplete_candle_is_logged_not_fatal(client: TestClient, auth: dict) -> None:
    candles = make_flat_candles(45)
    candles[-1]["isComplete"] = False  # незавершённая свеча — warning, но расчёт идёт
    resp = client.post("/indicators/calculate", json={"candles": candles}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["metadata"]["total_candles"] == 45
