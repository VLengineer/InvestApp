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
    -- competitors — TEXT по схеме init_db/03_init_company_profiles.sql,
    -- поэтому список конкурентов из cp.json передаётся уже склеенной строкой,
    -- а не JSON (иначе asyncpg отклонит запись list в текстовую колонку)
    $9, $10, $11::jsonb, $12,
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

    async def search_by_vector(
        self,
        vector_pg: str,
        limit: int = 5,
        *,
        min_similarity: float | None = None,
        recall_depth: int = 20,
    ) -> list[dict[str, Any]]:
        """Косинусный поиск по эмбеддингу профиля (pgvector ``<=>``).

        ``similarity`` — «сырое» косинусное сходство ``1 - distance``. У used
        эмбеддинг-модели (embeddinggemma) вектора сильного анизотропны:
        mean pairwise сходство профилей ~0.83, поэтому даже нерелевантный
        («мусорный») запрос даёт similarity ~0.65. Порог по сырому значению
        бессмысленен — он либо отсекает всё, либо ничего.

        Поэтому дополнительно считается ``rel_similarity`` — нормализованное
        «относительное» сходство относительно шумового пола данного запроса::

            rel = (similarity - avg_similarity) / (1 - avg_similarity)

        ``avg_similarity`` берётся по top-``recall_depth`` кандидатам (это и
        есть «пол» нерелевантности для конкретного запроса; самонастраивается
        при росте корпуса). Мусорный запрос даёт rel ~0.03–0.08, осмысленный —
        0.12–0.30. ``min_similarity`` фильтрует по rel_similarity; ``None`` —
        не фильтровать (прежнее поведение, просто top-``limit``).
        """
        async with self._database.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH cand AS (
                    SELECT company_name, ticker, figi, description, business_model, news_triggers,
                           1 - (embedding <=> $1::vector) AS similarity
                    FROM company_profiles
                    ORDER BY embedding <=> $1::vector
                    LIMIT $2
                ), agg AS (
                    SELECT AVG(similarity) AS mean_sim FROM cand
                )
                SELECT c.company_name, c.ticker, c.figi, c.description, c.business_model, c.news_triggers,
                       c.similarity,
                       (c.similarity - a.mean_sim) / GREATEST(1 - a.mean_sim, 1e-6) AS rel_similarity
                FROM cand c, agg a
                WHERE $3::float IS NULL
                   OR (c.similarity - a.mean_sim) / GREATEST(1 - a.mean_sim, 1e-6) >= $3
                ORDER BY c.similarity DESC
                LIMIT $4
                """,
                vector_pg,
                max(recall_depth, limit),
                min_similarity,
                limit,
            )
        return [dict(r) for r in rows]

    async def search_for_news(
        self,
        vector_pg: str,
        limit: int = 5,
        sector_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Косинусный поиск компаний под текст новости (эндпоинт /news/search-companies).

        Отличие от ``search_by_vector``: возвращаем полный профиль (JSONB-колонки),
        чтобы сервис собрал ``CompanyResult.profile`` без второго запроса к БД,
        и поддерживаем необязательный фильтр по сектору. Колонки ``sector``/
        ``sub_sector`` в схеме ``init_db/03_init_company_profiles.sql`` отсутствуют,
        поэтому фильтруем по склеенному тексту профиля ``embed_text`` (ILIKE).
        """
        async with self._database.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT company_name, ticker, figi, description, business_model,
                       market_position, competitors,
                       keywords_for_embedding, related_entities, news_triggers,
                       key_products, key_figures, historical_patterns,
                       embedding_model, embedding_dim,
                       1 - (embedding <=> $1::vector) AS similarity
                FROM company_profiles
                WHERE embedding IS NOT NULL
                  AND ($2::text IS NULL OR embed_text ILIKE '%' || $2 || '%')
                ORDER BY embedding <=> $1::vector
                LIMIT $3
                """,
                vector_pg,
                sector_filter,
                limit,
            )
        return [dict(r) for r in rows]
