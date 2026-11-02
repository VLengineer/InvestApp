"""Эндпоинты company_profiles (по подобию rag-роутера).

POST /company-profiles/ingest  — загрузить все профили из cp.json в БД (с эмбеддингами)
GET  /company-profiles         — список профилей
GET  /company-profiles/{figi}  — профиль по FIGI
POST /company-profiles/search  — векторный поиск похожих компаний

Все эндпоинты требуют авторизацию единым JWT-токеном
(``Authorization: Bearer <token>``) и проверяют scopes, как rag/news/indicators:
чтение/поиск — rag:read, ингест (запись в БД) — rag:index.

Слои: routes -> services (CompanyProfilesService) -> repositories -> БД.
Сервис получается через DI из Composition Root (app/core/container.py).
Путь к cp.json фиксирован (настраивается env COMPANY_PROFILES_JSON) —
в запросе указывать его не нужно.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import ContainerDep
from app.core.security import Principal, Scope, require_scope
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


@router.post(
    "/ingest",
    response_model=IngestResponse,
    summary="Загрузить профили из cp.json в БД (JWT, scope rag:index)",
)
async def ingest(
    service: CompanyProfilesDep,
    _principal: Annotated[Principal, Depends(require_scope(Scope.INDEX))],
) -> IngestResponse:
    """Заполнить таблицу company_profiles всеми объектами из cp.json.

    Путь к файлу фиксирован (``company_profiles/cp.json``, при необходимости
    переопределяется env ``COMPANY_PROFILES_JSON``) — указывать его в запросе
    не нужно; файл уже лежит в папке микросервиса и копируется в образ Docker.

    Для каждого профиля формируется склеенный текст (по приоритету полей),
    он эмбеддится моделью embeddinggemma-2 (768 dim) и upsert-ится в БД по figi.
    """
    try:
        result: dict[str, Any] = await service.ingest()
        return IngestResponse(**result)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"cp.json not found: {exc}. Файл должен лежать по пути "
                "company_profiles/cp.json внутри образа (/app/company_profiles/cp.json); "
                "путь можно переопределить env COMPANY_PROFILES_JSON"
            ),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ingest failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("", summary="Список профилей компаний (JWT, scope rag:read)")
async def list_profiles(
    service: CompanyProfilesDep,
    _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return await service.list_profiles(limit=limit, offset=offset)


@router.get("/{figi}", summary="Профиль компании по FIGI (JWT, scope rag:read)")
async def get_profile(
    service: CompanyProfilesDep,
    figi: str,
    _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
) -> dict[str, Any]:
    row = await service.get_profile(figi)
    if not row:
        raise HTTPException(status_code=404, detail=f"Profile {figi} not found")
    return row


@router.post("/search", summary="Векторный поиск похожих компаний (JWT, scope rag:read)")
async def search(
    req: SearchRequest,
    service: CompanyProfilesDep,
    _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
) -> list[dict[str, Any]]:
    try:
        return await service.search_similar(req.query, req.limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Search failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
