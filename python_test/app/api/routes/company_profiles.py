"""Эндпоинты company_profiles (по подобию rag-роутера).

POST /company-profiles/ingest  — загрузить все профили из cp.json в БД (с эмбеддингами)
GET  /company-profiles         — список профилей
GET  /company-profiles/{figi}  — профиль по FIGI
POST /company-profiles/search  — векторный поиск похожих компаний

Слои: routes -> services (CompanyProfilesService) -> repositories -> БД.
Сервис получается через DI из Composition Root (app/core/container.py).
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import ContainerDep
from app.services.company_profiles_service import CompanyProfilesService

logger = logging.getLogger(__name__)


def get_company_profiles_service(container: ContainerDep) -> CompanyProfilesService:
    return container.company_profiles


CompanyProfilesDep = Annotated[CompanyProfilesService, Depends(get_company_profiles_service)]

router = APIRouter(prefix="/company-profiles", tags=["company-profiles"])


class IngestResponse(BaseModel):
    total: int
    inserted: int
    updated: int
    failed: int


class SearchRequest(BaseModel):
    query: str = Field(..., description="Текст-запрос для эмбеддинга")
    limit: int = Field(5, ge=1, le=50)


@router.post("/ingest", response_model=IngestResponse)
async def ingest(service: CompanyProfilesDep, json_path: Optional[str] = None) -> IngestResponse:
    """Заполнить таблицу company_profiles всеми объектами из cp.json.

    Для каждого профиля формируется склеенный текст (по приоритету полей),
    он эмбеддится моделью embeddinggemma-2 (768 dim) и upsert-ится в БД по figi.
    """
    try:
        result: dict[str, Any] = await service.ingest(json_path)
        return IngestResponse(**result)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"cp.json not found: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ingest failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("")
async def list_profiles(
    service: CompanyProfilesDep, limit: int = 100, offset: int = 0
) -> list[dict[str, Any]]:
    return await service.list_profiles(limit=limit, offset=offset)


@router.get("/{figi}")
async def get_profile(service: CompanyProfilesDep, figi: str) -> dict[str, Any]:
    row = await service.get_profile(figi)
    if not row:
        raise HTTPException(status_code=404, detail=f"Profile {figi} not found")
    return row


@router.post("/search")
async def search(req: SearchRequest, service: CompanyProfilesDep) -> list[dict[str, Any]]:
    try:
        return await service.search_similar(req.query, req.limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Search failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
