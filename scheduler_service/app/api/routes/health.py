"""Эндпоинты, не требующие авторизации: liveness/readiness (паттерн python_test)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DatabaseDep, SettingsDep, WorkerDep
from app.schemas.scheduler import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/live", response_model=HealthResponse, summary="Liveness")
async def liveness(settings: SettingsDep, worker: WorkerDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        worker_alive=worker.alive,
        checks={},
    )


@router.get("/ready", response_model=HealthResponse, summary="Readiness (проверка БД)")
async def readiness(settings: SettingsDep, database: DatabaseDep, worker: WorkerDep) -> HealthResponse:
    db = await database.health()
    ok = db["status"] == "ok" and worker.alive
    return HealthResponse(
        status="ok" if ok else "degraded",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        worker_alive=worker.alive,
        checks={"postgres": db.get("detail", db["status"])},
    )
