"""Контракт API микросервиса news_analyzer (схемы запросов/ответов).

Формат тела совпадает с тем, что Vue-фронтенд отправляет на вебхук n8n
``POST http://n8n:5678/webhook/news_analizer``. Микросервис принимает этот JSON
и пересылает его на вебхук n8n (URL — из env ``N8N_BASE_URL`` + ``N8N_NEWS_WEBHOOK_PATH``); в БД пишет сценарий n8n.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NewsAnalyzeRequest(BaseModel):
    """Поля формы «Анализировать новость» (frontend → n8n webhook → backend)."""

    model_config = ConfigDict(extra="ignore")

    source: str = Field(min_length=1, max_length=255, description="Источник новости")
    title: str = Field(min_length=1, description="Заголовок")
    content: str = Field(min_length=1, description="Текст новости")
    ts: datetime = Field(description="Момент публикации (ISO 8601, наносекунды, UTC)")


class NewsAnalyzeResponse(BaseModel):
    """Ответ микросервиса: новость переслана на вебхук n8n, приложен его ответ."""

    forwarded: bool = True
    webhook_url: str = Field(description="URL вебхука, куда отправлена новость (env N8N_BASE_URL + N8N_NEWS_WEBHOOK_PATH)")
    status_code: int = Field(description="HTTP-код, которым ответил n8n")
    news: dict[str, Any] = Field(default_factory=dict, description="Отправленный JSON (source/title/content/ts)")
    n8n_response: Any = Field(default=None, description="Ответ вебхука n8n (JSON или {raw: текст})")
