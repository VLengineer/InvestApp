"""Сервис company_profiles: загрузка cp.json, склейка текста, эмбеддинги, запись в БД.

Логика полностью повторяет подход RAG-модуля:
  1) читаем источник (cp.json),
  2) формируем "склеенный" текст профиля по приоритету полей,
  3) получаем вектор через Ollama (embeddinggemma-2, dim=768),
  4) upsert-им строки в таблицу company_profiles (pgvector).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import asyncpg

from app.config import settings
from app.services.embeddings import embedding_client

logger = logging.getLogger(__name__)

NEWS_TRIGGER_CATEGORIES = ("positive", "negative", "neutral")


# --------------------------------------------------------------------------- #
# 1. Чтение JSON
# --------------------------------------------------------------------------- #
def load_company_profiles(path: str | None = None) -> list[dict[str, Any]]:
    path = path or settings.company_profiles_json
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):  # допускаем {"profiles": [...]}
        data = data.get("profiles") or data.get("companies") or list(data.values())
    if not isinstance(data, list):
        raise ValueError(f"Unexpected structure in {path}: expected list of profiles")
    return data


# --------------------------------------------------------------------------- #
# 2. Склейка текста для эмбеддинга (по приоритету полей)
# --------------------------------------------------------------------------- #
def _join_list(items: Any, sep: str = ", ") -> str:
    if items is None:
        return ""
    if isinstance(items, str):
        return items
    if isinstance(items, list):
        parts: list[str] = []
        for it in items:
            if isinstance(it, dict):
                # related_entities / key_figures: name + type/position
                name = it.get("name") or it.get("title") or ""
                extra = it.get("position") or it.get("type") or it.get("role") or ""
                parts.append(f"{name} ({extra})".strip("() "))
            else:
                parts.append(str(it))
        return sep.join(p for p in parts if p)
    return str(items)


def build_embed_text(profile: dict[str, Any]) -> str:
    """Склеить поля профиля в один текст согласно заданному приоритету."""
    nt = profile.get("news_triggers") or {}
    news_all: list[str] = []
    if isinstance(nt, dict):
        for cat in NEWS_TRIGGER_CATEGORIES:
            news_all.extend(str(x) for x in (nt.get(cat) or []))
    elif isinstance(nt, list):
        news_all = [str(x) for x in nt]

    identity = " ".join(
        str(profile[k]).strip()
        for k in ("company_name", "ticker", "figi")
        if profile.get(k)
    )

    ordered_fields: list[tuple[str, str]] = [
        ("Компания", identity),                                             # company_name + ticker + figi
        ("Описание", (profile.get("description") or "").strip()),           # description
        ("Бизнес-модель", (profile.get("business_model") or "").strip()),   # business_model
        ("Ключевые слова", _join_list(profile.get("keywords_for_embedding"))),
        ("Связанные сущности", _join_list(profile.get("related_entities"))),
        ("Новостные триггеры", _join_list(news_all)),                        # все три категории
        ("Ключевые продукты", _join_list(profile.get("key_products"))),
        ("Ключевые фигуры", _join_list(profile.get("key_figures"))),         # имена + должности
        ("Рыночная позиция", (profile.get("market_position") or "").strip()),
        ("Исторические паттерны", (profile.get("historical_patterns") or "").strip()),
        ("Целевая аудитория", (profile.get("target_audience") or "").strip()),
        ("География", (profile.get("geography") or "").strip()),
        ("Конкуренты", _join_list(profile.get("competitors"))),
        ("Регуляторные зависимости", (profile.get("regulatory_dependencies") or "").strip()),
        ("Технологический стек", _join_list(profile.get("technology_stack"))),
        ("Финансовые метрики", _join_list(profile.get("financial_metrics_of_interest"))),
        ("Факторы корреляции", _join_list(profile.get("correlation_factors"))),
    ]

    lines = [f"{label}: {value}" for label, value in ordered_fields if value]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 3. Вектор -> строка для pgvector
# --------------------------------------------------------------------------- #
def vector_to_pg(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


# --------------------------------------------------------------------------- #
# 4. Загрузка профилей в БД (по подобию rag ingest)
# --------------------------------------------------------------------------- #
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


async def ensure_table(pool: asyncpg.Pool) -> None:
    ddl_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "company_profiles", "03_init_company_profiles.sql"
    )
    with open(ddl_path, encoding="utf-8") as f:
        sql = f.read()
    async with pool.acquire() as conn:
        for stmt in filter(None, (s.strip() for s in sql.split(";"))):
            if not stmt.startswith("--"):
                await conn.execute(stmt)


async def get_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn=settings.dsn, min_size=1, max_size=5)


async def ingest_company_profiles(json_path: str | None = None) -> dict[str, Any]:
    """Основной процесс: cp.json -> эмбеддинги -> таблица company_profiles."""
    profiles = load_company_profiles(json_path)
    pool = await get_pool()
    try:
        await ensure_table(pool)
        inserted = updated = failed = 0
        async with pool.acquire() as conn:
            for prof in profiles:
                figi = (prof.get("figi") or "").strip() or None
                text = build_embed_text(prof)
                try:
                    embedding = embedding_client.embed(text)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Embedding failed for %s: %s", figi or prof.get("company_name"), exc)
                    failed += 1
                    continue

                exists = await conn.fetchval(
                    "SELECT 1 FROM company_profiles WHERE figi = $1", figi
                )
                await conn.execute(
                    UPSERT_SQL,
                    prof.get("company_name"),
                    prof.get("ticker"),
                    figi,
                    prof.get("description"),
                    prof.get("business_model"),
                    prof.get("market_position"),
                    prof.get("target_audience"),
                    prof.get("geography"),
                    json.dumps(prof.get("competitors"), ensure_ascii=False),
                    prof.get("regulatory_dependencies"),
                    json.dumps(prof.get("technology_stack"), ensure_ascii=False),
                    prof.get("historical_patterns"),
                    json.dumps(prof.get("keywords_for_embedding"), ensure_ascii=False),
                    json.dumps(prof.get("related_entities"), ensure_ascii=False),
                    json.dumps(prof.get("news_triggers"), ensure_ascii=False),
                    json.dumps(prof.get("key_products"), ensure_ascii=False),
                    json.dumps(prof.get("key_figures"), ensure_ascii=False),
                    json.dumps(prof.get("financial_metrics_of_interest"), ensure_ascii=False),
                    json.dumps(prof.get("correlation_factors"), ensure_ascii=False),
                    vector_to_pg(embedding),
                    embedding_client.model,
                    len(embedding),
                    text,
                )
                if exists:
                    updated += 1
                else:
                    inserted += 1
                logger.info("Upserted profile: %s (%s)", prof.get("company_name"), figi)

        return {
            "total": len(profiles),
            "inserted": inserted,
            "updated": updated,
            "failed": failed,
        }
    finally:
        await pool.close()


async def search_similar(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Косинусный поиск по эмбеддингу профиля (для эндпоинта /search)."""
    embedding = embedding_client.embed(query)
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT company_name, ticker, figi, description,
                       1 - (embedding <=> $1::vector) AS similarity
                FROM company_profiles
                ORDER BY embedding <=> $1::vector
                LIMIT $2
                """,
                vector_to_pg(embedding),
                limit,
            )
        return [dict(r) for r in rows]
    finally:
        await pool.close()
