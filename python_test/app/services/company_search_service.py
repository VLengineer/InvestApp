"""Сервис семантического поиска компаний по тексту новости.

Слои проекта: routes -> services -> repositories -> БД (как в
``company_profiles_service`` / ``news_analyzer.service``).

Цепочка запроса ``POST /news/search-companies``:
  1) текст новости эмбеддится через Ollama (переиспользуем готовый клиент
     ``app/clients/ollama.py`` — Circuit Breaker + retry + таймауты уже там);
  2) косинусный поиск по таблице ``company_profiles`` (pgvector ``<=>``,
     similarity = 1 - distance) через ``CompanyProfileRepository``;
  3) результаты фильтруются по ``min_similarity`` и упаковываются в схемы
     ``app/schemas/news.py``.

Эмбеддинг запроса формируется с префиксом ``search: `` — так же, как в
``CompanyProfilesService.search_similar`` (единый промпт-формат для модели).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from app.clients.ollama import OllamaEmbeddingClient
from app.core.config import Settings
from app.schemas.news import CompanyResult, NewsSearchRequest, NewsSearchResponse
from app.services.company_profiles_service import vector_to_pg

if TYPE_CHECKING:  # только для типов; рантайм-импорт не нужен
    from app.repositories.company_profile_repository import CompanyProfileRepository

logger = logging.getLogger(__name__)


def _to_jsonable(value: Any) -> Any:
    """Привести значение строки БД к JSON-совместимому виду для схемы ``profile``.

    asyncpg возвращает jsonb уже как dict/list, а даты/timestamps и Decimal —
    нет; приводим их к ISO-строкам/float, чтобы CompanyResult.profile сериализовался
    без дополнительных костылей на уровне роута.
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


class CompanySearchService:
    """Семантический поиск компаний-эмитентов под текст новости."""

    def __init__(
        self,
        settings: Settings,
        embedder: OllamaEmbeddingClient,
        repository: "CompanyProfileRepository",
    ) -> None:
        self._settings = settings
        self._embedder = embedder
        self._repository = repository

    async def search_companies(
        self,
        news_embedding: list[float],
        top_k: int = 5,
        min_similarity: float = 0.5,
        sector_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Косинусный поиск по готовому эмбеддингу новости (pgvector ``<=>``).

        Берёт ``top_k`` ближайших профилей (с необязательным фильтром по сектору),
        затем отсекает строки с ``similarity < min_similarity``. Сходство
        считается как ``1 - cosine distance`` прямо в SQL.
        """
        rows = await self._repository.search_for_news(
            vector_to_pg(news_embedding),
            limit=top_k,
            sector_filter=sector_filter,
        )
        filtered = [row for row in rows if float(row["similarity"]) >= min_similarity]
        logger.info(
            "company_search >>> top_k=%d min_similarity=%.2f sector=%r: найдено %d, прошло порог %d",
            top_k, min_similarity, sector_filter, len(rows), len(filtered),
        )
        return filtered

    async def search_by_news(self, request: NewsSearchRequest) -> NewsSearchResponse:
        """Полный цикл: текст новости -> эмбеддинг Ollama -> pgvector -> ответ API."""
        embedding = await self._embedder.embed(f"search: {request.news_text}")
        rows = await self.search_companies(
            embedding,
            top_k=request.top_k,
            min_similarity=request.min_similarity,
            sector_filter=request.sector_filter,
        )
        results = [
            CompanyResult(
                company_name=row["company_name"],
                ticker=row.get("ticker"),
                figi=row.get("figi"),
                similarity=round(float(row["similarity"]), 6),
                profile={k: _to_jsonable(v) for k, v in row.items() if k != "company_name"},
            )
            for row in rows
        ]
        logger.info(
            "company_search <<< news (%d симв.): %d компаний (model=%s, dim=%d)",
            len(request.news_text), len(results),
            self._settings.embedding_model, len(embedding),
        )
        return NewsSearchResponse(
            results=results,
            query_embedding_dim=len(embedding),
            model=self._settings.embedding_model,
        )
