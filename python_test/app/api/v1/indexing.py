"""API микросервиса индексации базы знаний.

Эндпоинты:
  POST /api/v1/index/run     — запустить индексацию (фоновая задача)
  GET  /api/v1/index/status  — прогресс последней/текущей индексации
  POST /api/v1/index/cancel  — остановить индексацию
  POST /api/v1/search        — семантический поиск по RAG-хранилищу
  GET  /api/v1/stats         — содержимое хранилища
"""

from __future__ import annotations

import logging

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import Settings, get_settings
from app.dependencies import require_jwt
from app.schemas.indexing import (
    IndexRequest,
    IndexStatusResponse,
    SearchRequest,
    SearchResponse,
)
from app.services.storage import RagStorage

log = logging.getLogger("python_test.api")

router = APIRouter(tags=["rag-indexer"])

Auth = Annotated[dict, Depends(require_jwt)]


def _indexer(request: Request):
    return request.app.state.indexer


def _storage(request: Request) -> RagStorage:
    return request.app.state.storage


@router.post("/index/run", response_model=IndexStatusResponse, status_code=202)
async def run_index(payload: IndexRequest, request: Request, _user: Auth) -> dict:
    """Запускает индексацию knowledge_base в фоне."""
    indexer = _indexer(request)
    try:
        progress = indexer.start(full_refresh=payload.full_refresh)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return progress.as_dict()


@router.get("/index/status", response_model=IndexStatusResponse)
async def index_status(request: Request, _user: Auth) -> dict:
    return _indexer(request).progress.as_dict()


@router.post("/index/cancel", response_model=IndexStatusResponse)
async def cancel_index(request: Request, _user: Auth) -> dict:
    indexer = _indexer(request)
    if not indexer.busy:
        raise HTTPException(status_code=409, detail="Индексация не выполняется")
    await indexer.cancel()
    return indexer.progress.as_dict()


@router.post("/search", response_model=SearchResponse)
async def search(
    payload: SearchRequest,
    request: Request,
    _user: Auth,
    settings: Settings = Depends(get_settings),
) -> SearchResponse:
    """Эмбеддит запрос моделью embeddinggemma-2 и ищет ближайшие документы."""
    embedder = request.app.state.embedder
    try:
        vectors = await embedder.embed([payload.query])
    except Exception as exc:  # noqa: BLE001
        log.exception("Ошибка эмбеддинга запроса")
        raise HTTPException(status_code=502, detail=f"Ollama недоступна: {exc}")
    hits = await _storage(request).search(
        vectors[0], limit=payload.limit, min_similarity=payload.min_similarity
    )
    for h in hits:
        h["similarity"] = round(float(h["similarity"]), 6)
    return SearchResponse(query=payload.query, model=settings.ollama_embed_model, hits=hits)


@router.get("/stats")
async def stats(request: Request, _user: Auth) -> dict:
    return await _storage(request).stats()


@router.get("/health")
async def health(request: Request, settings: Settings = Depends(get_settings)) -> dict:
    """Диагностика: доступность PostgreSQL и Ollama (без JWT — используется docker healthcheck)."""
    out: dict = {"status": "ok", "model": settings.ollama_embed_model}
    try:
        out["db"] = await _storage(request).stats()
    except Exception as exc:  # noqa: BLE001
        out["db"] = {"error": str(exc)}
        out["status"] = "degraded"
    try:
        out["ollama"] = await request.app.state.embedder.health()
    except Exception as exc:  # noqa: BLE001
        out["ollama"] = {"error": str(exc)}
        out["status"] = "degraded"
    return out
