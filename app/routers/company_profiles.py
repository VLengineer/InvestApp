"""Эндпоинты company_profiles (по подобию rag-роутера).

POST /company-profiles/ingest  — загрузить все профили из cp.json в БД (с эмбеддингами)
GET  /company-profiles         — список профилей
GET  /company-profiles/{figi}  — профиль по FIGI
POST /company-profiles/search  — векторный поиск похожих компаний
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.company_profiles_service import (
    get_pool,
    ingest_company_profiles,
    search_similar,
)

logger = logging.getLogger(__name__)

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
async def ingest(json_path: Optional[str] = None) -> IngestResponse:
    """Заполнить таблицу company_profiles всеми объектами из cp.json.

    Для каждого профиля формируется склеенный текст (по приоритету полей),
    он эмбеддится моделью embeddinggemma-2 (768 dim) и upsert-ится в БД по figi.
    """
    try:
        result: dict[str, Any] = await ingest_company_profiles(json_path)
        return IngestResponse(**result)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"cp.json not found: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ingest failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("")
async def list_profiles(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, company_name, ticker, figi, description, business_model,
                       market_position, embedding_model, embedding_dim,
                       created_at, updated_at
                FROM company_profiles
                ORDER BY id
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
        return [dict(r) for r in rows]
    finally:
        await pool.close()


@router.get("/{figi}")
async def get_profile(figi: str) -> dict[str, Any]:
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM company_profiles WHERE figi = $1", figi
            )
        if not row:
            raise HTTPException(status_code=404, detail=f"Profile {figi} not found")
        return dict(row)
    finally:
        await pool.close()


@router.post("/search")
async def search(req: SearchRequest) -> list[dict[str, Any]]:
    try:
        return await search_similar(req.query, req.limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Search failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
