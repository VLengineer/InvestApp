"""Эндпоинты, не требующие авторизации: liveness/readiness."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ContainerDep, SettingsDep
from app.schemas.api_schemas import HealthResponse

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


@router.get("/ready", response_model=HealthResponse, summary="Readiness (проверка БД и Ollama)")
async def readiness(container: ContainerDep, settings: SettingsDep) -> HealthResponse:
    db = await container.database.health()
    ollama = await container.embedder.health()
    ok = db["status"] == "ok" and ollama["status"] == "ok"
    return HealthResponse(
        status="ok" if ok else "degraded",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        checks={"postgres": db.get("detail", db["status"]), "ollama": ollama.get("detail", ollama["status"])},
    )
