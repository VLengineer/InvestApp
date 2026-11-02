"""Pydantic-схемы семантического поиска компаний по новостям.

Контракт эндпоинта ``POST /news/search-companies`` (ТЗ, раздел 3.4):
вход — текст новости + параметры top_k/min_similarity/sector_filter,
выход — список компаний с косинусной similarity и полным профилем.

Именование полей — snake_case, как в остальных схемах проекта
(``app/schemas/api_schemas.py``, ``app/news_analyzer/schemas.py``).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NewsSearchRequest(BaseModel):
    """Тело запроса: новость и параметры векторного поиска."""

    model_config = ConfigDict(extra="ignore")

    news_text: str = Field(
        ...,
        min_length=10,
        description="Текст новости (заголовок или фрагмент) для эмбеддинга и поиска",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Сколько наиболее похожих компаний вернуть",
    )
    min_similarity: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Минимальный порог косинусной близости (1 - cosine distance)",
    )
    sector_filter: str | None = Field(
        default=None,
        description=(
            "Необязательная подстрока сектора; поиск идёт по тексту профиля "
            "(ILIKE), например 'банк' оставит только банковские компании"
        ),
    )


class CompanyResult(BaseModel):
    """Одна найденная компания с метрой сходства и профилем из БД."""

    company_name: str
    ticker: str | None = None
    figi: str | None = None
    similarity: float = Field(description="Косинусная близость эмбеддингов, 0..1")
    profile: dict[str, Any] = Field(default_factory=dict, description="Полный профиль компании")


class NewsSearchResponse(BaseModel):
    """Ответ поиска: отфильтрованные результаты + метаданные запроса."""

    results: list[CompanyResult] = Field(default_factory=list)
    query_embedding_dim: int = Field(description="Размерность эмбеддинга запроса (например, 768)")
    model: str = Field(description="Использованная эмбеддинг-модель Ollama")
