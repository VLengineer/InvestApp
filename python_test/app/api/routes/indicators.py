"""Эндпоинты расчёта технических индикаторов и аналитики по свечным данным.

POST /indicators/calculate — принимает массив свечей в формате T-Invest API
(``units`` + ``nano``), возвращает 9 индикаторов для каждой свечи + аналитику
(гэпы, аномалии объёма, тренды, свечные паттерны, режим волатильности, моментум).

Авторизация — единым JWT-токеном проекта (Scope.READ), как у остальных эндпоинтов.
Сервис не обращается к БД/Ollama, поэтому инстанцируется напрямую (stateless).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.security import Principal, Scope, require_scope
from app.schemas.indicators import IndicatorsRequest, IndicatorsResponse
from app.services.indicators_service import IndicatorsService

router = APIRouter(prefix="/indicators", tags=["indicators"])

_service = IndicatorsService()


@router.post(
    "/calculate",
    response_model=IndicatorsResponse,
    summary="Расчёт технических индикаторов и аналитики по свечам",
    description=(
        "Вход: свечи T-Invest API (`open/high/low/close` в формате `{units, nano}`, "
        "`volume`, `volumeBuy`, `volumeSell`, `time`).\n\n"
        "Индикаторы: RSI(14), Stochastic(14,3,3), MACD(12,26,9), CCI(20), Williams %R(14), "
        "MFI(14), ADX(14), ROC(12), ATR(14) — расчёт через `pandas-ta`.\n\n"
        "Правила: минимум 40 свечей (иначе 400); первые 40 свечей — `is_valid: false` "
        "(warmup period); несоответствие порядка по времени сортируется автоматически; "
        "пропуски во времени логируются как warning, но не останавливают расчёт.\n\n"
        "Аналитика: гэпы (|gap| > 0.05%), аномалии объёма (> 3×SMA20), тренды (5+ свечей), "
        "паттерны (engulfing, hammer/inverted_hammer, doji), режим волатильности (ATR/ATR20), "
        "моментум (ROC12 + ускорение).\n\n"
        "Дополнительно в корне ответа — `last_candle_rsi`: RSI(14) последней свечи "
        "входного набора (`timestamp` + `rsi_14`)."
    ),
    responses={
        400: {
            "description": "Недостаточно свечей для расчёта",
            "content": {
                "application/json": {
                    "example": {
                        "code": "not_enough_candles",
                        "message": "Минимум 40 свечей для расчета индикаторов",
                        "details": {},
                    }
                }
            },
        }
    },
)
async def calculate_indicators(
    body: IndicatorsRequest,
    _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
) -> IndicatorsResponse:
    """Основной эндпоинт сервиса теханализа (синхронный CPU-расчёт)."""
    return _service.calculate(body)
