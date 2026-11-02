"""Эндпоинты микросервиса news_analyzer (код сервиса — в python_test/news_analyzer).

Соглашение проекта: каждый микросервис имеет свою папку внутри python_test/,
а его HTTP-эндпоинты подключаются отдельным файлом роутов здесь.

POST /news/analyze — принимает новость {source, title, content, ts} и сохраняет
её в market_news_ml_dataset. Вызывается из сценария n8n, который подписывает
запрос единым JWT-токеном (webhook ``news_analizer`` ← Vue-фронтенд).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import ContainerDep, NewsAnalyzerDep
from app.core.security import Principal, Scope, require_scope
from news_analyzer.schemas import NewsAnalyzeRequest, NewsAnalyzeResponse

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
