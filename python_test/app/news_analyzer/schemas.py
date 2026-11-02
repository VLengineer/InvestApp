"""Контракт API микросервиса news_analyzer (схемы запросов/ответов).

Формат тела совпадает с тем, что Vue-фронтенд отправляет на вебхук n8n
``POST http://n8n:5678/webhook/news_analizer`` и что бэкенд сохраняет
в таблицу ``market_news_ml_dataset``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NewsAnalyzeRequest(BaseModel):
    """Поля формы «Анализировать новость» (frontend → n8n webhook → backend)."""

    model_config = ConfigDict(extra="ignore")

    source: str = Field(min_length=1, max_length=255, description="Источник новости")
    title: str = Field(min_length=1, description="Заголовок")
    content: str = Field(min_length=1, description="Текст новости")
    ts: datetime = Field(description="Момент публикации (ISO 8601, наносекунды, UTC)")


class NewsAnalyzeResponse(BaseModel):
    """Ответ бэкенда: запись сохранена в market_news_ml_dataset."""

    id: UUID
    source: str
    title: str
    ts: datetime
    saved: bool = True
    table: str = "market_news_ml_dataset"
    detail: dict[str, Any] = Field(default_factory=dict)
