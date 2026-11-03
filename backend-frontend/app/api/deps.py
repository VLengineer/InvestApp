"""Зависимости API-слоя backend-frontend (паттерн python_test/scheduler_service app/api/deps.py):
объекты живут в app.state (собираются в lifespan), зависимости — тонкие геттеры."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings
from app.db.database import Database
from app.services.market_service import MarketService

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_database(request: Request) -> Database:
    database: Database | None = getattr(request.app.state, "database", None)
    if database is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="БД ещё не подключена")
    return database


def get_market_service(request: Request) -> MarketService:
    service: MarketService | None = getattr(request.app.state, "market_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Сервис рынка ещё не готов")
    return service


DatabaseDep = Annotated[Database, Depends(get_database)]
MarketServiceDep = Annotated[MarketService, Depends(get_market_service)]
