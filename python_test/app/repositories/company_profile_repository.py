"""Репозиторий таблицы ``company_profiles`` (asyncpg + pgvector).

Слои проекта: routes -> services -> repositories -> БД.
Репозиторий принимает живой объект ``app.db.database.Database`` и берёт у него
пул в момент вызова — поэтому репозиторий можно собрать до подключения БД
(тот же приём, что ``NewsRepository`` для микросервиса news_analyzer).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.db.company_profiles_schema import ensure_company_profiles_table

if TYPE_CHECKING:  # только для типов; рантайм-импорт не нужен
    from app.db.database import Database

logger = logging.getLogger(__name__)

UPSERT_SQL = """
INSERT INTO company_profiles (
    company_name, ticker, figi,
    description, business_model, market_position, target_audience, geography,
    competitors, regulatory_dependencies, technology_stack, historical_patterns,
    keywords_for_embedding, related_entities, news_triggers, key_products,
    key_figures, financial_metrics_of_interest, correlation_factors,
    embedding, embedding_model, embedding_dim, embed_text,
    created_at, updated_at
) VALUES (
    $1, $2, $3,
    $4, $5, $6, $7, $8,
    $9::jsonb, $10, $11::jsonb, $12,
    $13::jsonb, $14::jsonb, $15::jsonb, $16::jsonb,
    $17::jsonb, $18::jsonb, $19::jsonb,
    $20::vector, $21, $22, $23,
    now(), now()
)
ON CONFLICT (figi) DO UPDATE SET
    company_name                = EXCLUDED.company_name,
    ticker                      = EXCLUDED.ticker,
    description                 = EXCLUDED.description,
    business_model              = EXCLUDED.business_model,
    market_position             = EXCLUDED.market_position,
    target_audience             = EXCLUDED.target_audience,
    geography                   = EXCLUDED.geography,
    competitors                 = EXCLUDED.competitors,
    regulatory_dependencies     = EXCLUDED.regulatory_dependencies,
    technology_stack            = EXCLUDED.technology_stack,
    historical_patterns         = EXCLUDED.historical_patterns,
    keywords_for_embedding      = EXCLUDED.keywords_for_embedding,
    related_entities            = EXCLUDED.related_entities,
    news_triggers               = EXCLUDED.news_triggers,
    key_products                = EXCLUDED.key_products,
    key_figures                 = EXCLUDED.key_figures,
    financial_metrics_of_interest = EXCLUDED.financial_metrics_of_interest,
    correlation_factors         = EXCLUDED.correlation_factors,
    embedding                   = EXCLUDED.embedding,
    embedding_model             = EXCLUDED.embedding_model,
    embedding_dim               = EXCLUDED.embedding_dim,
    embed_text                  = EXCLUDED.embed_text,
    updated_at                  = now()
"""


class CompanyProfileRepository:
    """Доступ к таблице company_profiles (DDL идемпотентна, IF NOT EXISTS)."""

    def __init__(self, database: "Database") -> None:
        self._database = database

    async def ensure_schema(self) -> None:
        """Создать таблицу, если её ещё нет (для локального запуска без init_db)."""
        async with self._database.pool.acquire() as conn:
            await ensure_company_profiles_table(conn)

    async def exists(self, figi: str | None) -> bool:
        if not figi:
            return False
        async with self._database.pool.acquire() as conn:
            found = await conn.fetchval("SELECT 1 FROM company_profiles WHERE figi = $1", figi)
        return found is not None

    async def upsert_profile(self, values: tuple) -> None:
        """Выполнить upsert одной строки профиля (см. UPSERT_SQL, 23 параметра)."""
        async with self._database.pool.acquire() as conn:
            await conn.execute(UPSERT_SQL, *values)

    async def list_profiles(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        async with self._database.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, company_name, ticker, figi, description, business_model,
                       market_position, embedding_model, embedding_dim,
                       created_at, updated_at
                FROM company_profiles
                ORDER BY id
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
        return [dict(r) for r in rows]

    async def get_by_figi(self, figi: str) -> dict[str, Any] | None:
        async with self._database.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM company_profiles WHERE figi = $1", figi)
        return dict(row) if row else None

    async def search_by_vector(self, vector_pg: str, limit: int = 5) -> list[dict[str, Any]]:
        """Косинусный поиск по эмбеддингу профиля (pgvector ``<=>``)."""
        async with self._database.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT company_name, ticker, figi, description,
                       1 - (embedding <=> $1::vector) AS similarity
                FROM company_profiles
                ORDER BY embedding <=> $1::vector
                LIMIT $2
                """,
                vector_pg,
                limit,
            )
        return [dict(r) for r in rows]
