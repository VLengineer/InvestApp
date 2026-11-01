"""Бизнес-логика микросервиса news_analyzer.

Микросервис НЕ работает с БД: он принимает новость из формы
``{source, title, content, ts}`` и пересылает её POST-запросом на вебхук n8n
env ``N8N_BASE_URL`` + ``N8N_NEWS_WEBHOOK_PATH`` (по умолчанию http://n8n:5678/webhook/news_analizer).
Дальше — сохранение в ``market_news_ml_dataset`` и AI-анализ — делает сценарий n8n.
"""

from __future__ import annotations

import logging
from typing import Any

from news_analyzer.client import N8nWebhookClient
from news_analyzer.schemas import NewsAnalyzeRequest, NewsAnalyzeResponse

logger = logging.getLogger(__name__)


class NewsAnalyzerService:
    def __init__(self, client: N8nWebhookClient) -> None:
        self._client = client

    async def analyze(self, request: NewsAnalyzeRequest) -> NewsAnalyzeResponse:
        """Пересылает новость на вебхук n8n и возвращает его ответ."""
        logger.info(
            "news_analyzer >>> analyze: source=%r title=%r content_len=%d ts=%s → %s",
            request.source, request.title, len(request.content), request.ts.isoformat(),
            self._client.webhook_url,
        )
        forwarded: dict[str, Any] = await self._client.forward_news(request)
        logger.info("news_analyzer <<< n8n ответил HTTP %s", forwarded["status_code"])
        return NewsAnalyzeResponse(
            forwarded=True,
            webhook_url=self._client.webhook_url,
            status_code=forwarded["status_code"],
            news={
                "source": request.source,
                "title": request.title,
                "content": request.content,
                "ts": request.ts,
            },
            n8n_response=forwarded["response"],
        )

    async def health(self) -> dict[str, str]:
        return await self._client.health()
