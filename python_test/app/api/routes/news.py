"""Эндпоинты микросервиса news_analyzer (код сервиса — в python_test/news_analyzer).

Соглашение проекта: каждый микросервис имеет свою папку внутри python_test/,
а его HTTP-эндпоинты подключаются отдельным файлом роутов здесь.

POST /news/analyze — принимает новость {source, title, content, ts} и ПЕРЕСЫЛАЕТ
её на вебхук n8n (URL берётся из env N8N_BASE_URL + N8N_NEWS_WEBHOOK_PATH, по умолчанию
http://n8n:5678/webhook/news_analizer). Сам микросервис в БД НЕ пишет —
сохранением в market_news_ml_dataset и анализом занимается сценарий n8n.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import NewsAnalyzerDep
from app.core.security import Principal, Scope, require_scope
from news_analyzer.client import N8nForwardError
from news_analyzer.schemas import NewsAnalyzeRequest, NewsAnalyzeResponse

router = APIRouter(prefix="/news", tags=["news_analyzer"])


@router.post(
    "/analyze",
    response_model=NewsAnalyzeResponse,
    summary="Переслать новость на вебхук n8n (news_analizer)",
    description=(
        "Микросервис не сохраняет новость сам: он отправляет JSON "
        "{source, title, content, ts} POST-запросом на вебхук n8n "
        "(env N8N_BASE_URL + N8N_NEWS_WEBHOOK_PATH, по умолчанию http://n8n:5678/webhook/news_analizer) "
        "и возвращает ответ n8n. Дальнейшее сохранение в market_news_ml_dataset — "
        "зона ответственности сценария n8n."
    ),
    responses={
        502: {"description": "n8n недоступна или вернула HTTP ошибку"},
    },
)
async def analyze_news(
    body: NewsAnalyzeRequest,
    service: NewsAnalyzerDep,
    _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
) -> NewsAnalyzeResponse:
    try:
        return await service.analyze(body)
    except N8nForwardError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "n8n_forward_failed",
                "message": str(exc),
                "n8n_status": exc.status_code,
                "n8n_body": exc.body,
            },
        ) from exc


@router.get(
    "/health",
    summary="Доступность n8n (вебхук-сервер)",
)
async def news_health(
    service: NewsAnalyzerDep,
    _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
) -> dict[str, Any]:
    return await service.health()
