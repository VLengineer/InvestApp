"""Эндпоинты, не требующие авторизации: liveness/readiness (паттерн scheduler_service)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DatabaseDep, MarketServiceDep, SettingsDep
from app.schemas.market_data import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/live", response_model=HealthResponse, summary="Liveness")
async def liveness(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        checks={},
    )


@router.get("/ready", response_model=HealthResponse, summary="Readiness (проверка БД)")
async def readiness(
    settings: SettingsDep, database: DatabaseDep, market: MarketServiceDep
) -> HealthResponse:
    db = await database.health()
    ok = db["status"] == "ok"
    return HealthResponse(
        status="ok" if ok else "degraded",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        checks={
            "postgres": db.get("detail", db["status"]),
            "ws_subscribers": str(len(market.subscribed_figis)),
        },
    )
