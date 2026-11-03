"""REST-эндпоинты рынка для Vue-дашборда: /api/market/*.

Валидация на бэкенде (требование ТЗ «Безопасность»):
  * FIGI проверяется на реальное существование в БД (не доверяем query-параметру);
  * id новости — UUID (парсится схемой, битый формат = 422);
  * limit истории жёстко ограничен сервисом (500).

WebSocket живёт отдельно — app/routers/websocket.py (монтируется в main.py).
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, status

from app.api.deps import MarketServiceDep
from app.schemas.market_data import (
    FigiListResponse,
    InitialDataResponse,
    NewsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market", tags=["market"])

# FIGI валидируется по формату T-Invest (буквы/цифры, до 32 симв.) + проверкой в БД.
FigiParam = Annotated[
    str,
    Query(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$", description="FIGI инструмента"),
]


@router.get("/figis", response_model=FigiListResponse, summary="Список FIGI с данными")
async def list_figis(market: MarketServiceDep) -> FigiListResponse:
    """Уникальные FIGI, по которым есть записи в market_news_ml_dataset."""
    figis = await market.list_figis()
    return FigiListResponse(figis=figis)


@router.get(
    "/initial-data",
    response_model=InitialDataResponse,
    summary="Последние 500 записей для конкретного FIGI",
    responses={404: {"description": "FIGI не найден в БД"}},
)
async def initial_data(
    market: MarketServiceDep, figi: FigiParam
) -> InitialDataResponse:
    """История для начальной отрисовки графиков (хронологический порядок)."""
    items = await market.initial_data(figi)
    if items is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"FIGI {figi} не найден среди данных в БД",
        )
    return InitialDataResponse(data=items, figi=figi)


@router.get(
    "/news/{news_id}",
    response_model=NewsResponse,
    summary="Полная информация о новости по ID",
    responses={404: {"description": "Новость не найдена"}},
)
async def news_by_id(
    market: MarketServiceDep,
    news_id: Annotated[UUID, Path(description="id записи market_news_ml_dataset")],
) -> NewsResponse:
    """Полная запись новости (для модалки NewsModal по клику на маркер графика)."""
    item = await market.news_by_id(news_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Новость {news_id} не найдена",
        )
    return NewsResponse(news=item)
