"""Эндпоинты микросервиса news_analyzer (код сервиса — в python_test/news_analyzer).

Соглашение проекта: каждый микросервис имеет свою папку внутри python_test/,
а его HTTP-эндпоинты подключаются отдельным файлом роутов здесь.

POST /news/analyze — принимает новость {source, title, content, ts} и сохраняет
её в market_news_ml_dataset. Вызывается из сценария n8n, который подписывает
запрос единым JWT-токеном (webhook ``news_analizer`` ← Vue-фронтенд).

POST /news/search-companies — семантический поиск компаний-эмитентов по тексту
новости через эмбеддинги (Ollama) и pgvector (таблица company_profiles).
Код сервиса — app/services/company_search_service.py.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import CompanySearchDep, ContainerDep, NewsAnalyzerDep
from app.core.security import Principal, Scope, require_scope
from app.news_analyzer.schemas import NewsAnalyzeRequest, NewsAnalyzeResponse
from app.schemas.news import NewsSearchRequest, NewsSearchResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/news", tags=["news_analyzer"])


@router.post(
    "/analyze",
    response_model=NewsAnalyzeResponse,
    summary="Сохранить новость в ML-датасет (market_news_ml_dataset)",
    description=(
        "Цепочка: Vue-форма → POST http://n8n:5678/webhook/news_analizer → "
        "сценарий n8n вызывает этот эндпоинт с JWT. Тело совпадает с полями формы: "
        "source, title, content, ts (ISO 8601 с наносекундами)."
    ),
)
async def analyze_news(
    body: NewsAnalyzeRequest,
    service: NewsAnalyzerDep,
    principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
) -> NewsAnalyzeResponse:
    return await service.analyze(body)


@router.get(
    "/health",
    summary="Статус таблицы news-датасета",
)
async def news_health(
    container: ContainerDep,
    _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
) -> dict[str, Any]:
    return await container.news_repository.health()


@router.post(
    "/search-companies",
    response_model=NewsSearchResponse,
    summary="Семантический поиск компаний по тексту новости (JWT, scope rag:read)",
    description=(
        "Текст новости эмбеддится через Ollama, затем выполняется косинусный "
        "поиск (pgvector <=>) по таблице company_profiles. Возвращаются компании "
        "с similarity >= min_similarity (не более top_k) и их полными профилями. "
        "sector_filter — необязательная подстрока, фильтрует по тексту профиля (ILIKE). "
        "Перед использованием загрузите профили: POST /company-profiles/ingest."
    ),
)
async def search_companies_by_news(
    request: NewsSearchRequest,
    service: CompanySearchDep,
    _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
) -> NewsSearchResponse:
    """1) эмбеддинг news_text через Ollama; 2) pgvector-поиск; 3) фильтр по порогу."""
    try:
        return await service.search_by_news(request)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        # EmbeddingError (Ollama недоступна/модель не загружена) или ошибка БД —
        # единый понятный 500, как в /company-profiles/search.
        logger.exception("News search failed")
        raise HTTPException(status_code=500, detail=f"Поиск компаний по новости не удался: {exc}") from exc
