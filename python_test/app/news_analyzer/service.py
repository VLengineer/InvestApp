"""Бизнес-логика микросервиса news_analyzer.

Принимает новость из формы (Vue → n8n webhook → POST /news/analyze),
сохраняет базовые поля в ``market_news_ml_dataset``. AI/рыночные фичи
(rsi/macd/sentiment/target…) остаются NULL и дозаполняются позже
пайплайном n8n/Ollama по id записи.
"""

from __future__ import annotations

import logging
from typing import Any

from app.news_analyzer.repository import NEWS_TABLE, NewsRepository
from app.news_analyzer.schemas import NewsAnalyzeRequest, NewsAnalyzeResponse

logger = logging.getLogger(__name__)


class NewsAnalyzerService:
    def __init__(self, repository: NewsRepository) -> None:
        self._repository = repository

    async def analyze(self, request: NewsAnalyzeRequest) -> NewsAnalyzeResponse:
        """Сохраняет новость в датасет и возвращает созданный id."""
        logger.info(
            "news_analyzer >>> analyze: source=%r title=%r content_len=%d ts=%s",
            request.source, request.title, len(request.content), request.ts.isoformat(),
        )
        row = await self._repository.insert_news(
            source=request.source,
            title=request.title,
            content=request.content,
            ts=request.ts,
        )
        detail: dict[str, Any] = {"table": NEWS_TABLE, "ai_fields": "pending (заполняет n8n/Ollama)"}
        logger.info("news_analyzer <<< сохранено id=%s", row["id"])
        return NewsAnalyzeResponse(
            id=row["id"],
            source=row["source"],
            title=row["title"],
            ts=row["ts"],
            saved=True,
            table=NEWS_TABLE,
            detail=detail,
        )
