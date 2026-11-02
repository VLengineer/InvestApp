"""Загрузка профилей компаний (cp.json) в таблицу ``company_profiles`` с эмбеддингами.

Полный цикл (ТЗ, раздел 3.1):
  1) читаем профили из ``python_test/company_profiles/cp.json``
     (путь переопределяется env ``COMPANY_PROFILES_JSON``);
  2) склеиваем поля каждого профиля в ``embedding_text`` — функция
     :func:`build_embedding_text` ниже;
  3) получаем вектор через Ollama (async-клиент ``app/clients/ollama.py``:
     retry + circuit breaker уже внутри);
  4) UPSERT в ``company_profiles`` по ``figi`` (pgvector, таблица vector(768)).

Примечание про источник данных: в этом проекте файл профилей лежит в
``python_test/company_profiles/cp.json`` (в ТЗ он назван
``data/company_profiles.json``), содержит 10 компаний и полностью совпадает
со схемой таблицы ``init_db/03_init_company_profiles.sql``; обязательные поля
``build_embedding_text`` читает через ``.get()`` с пустыми значениями по
умолчанию, поэтому работает и с более коротким набором полей.

Запуск (из контейнера, как в ТЗ):
    docker exec -it python_test python -m scripts.seed_company_profiles

Локально (из папки python_test/):
    python -m scripts.seed_company_profiles [--json path/to/cp.json]

Логика upsert/эмбеддингов переиспользует CompanyProfilesService — скрипт не
дублирует код инджеста, а лишь добавляет форматированный embedding_text
(функция build_embedding_text) перед вызовом сервиса.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

# делаем пакет app импортируемым при запуске скрипта напрямую
ROOT = Path(__file__).resolve().parents[1]  # python_test/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.clients.ollama import OllamaEmbeddingClient  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.database import Database  # noqa: E402
from app.repositories.company_profile_repository import CompanyProfileRepository  # noqa: E402
from app.services.company_profiles_service import (  # noqa: E402
    CompanyProfilesService,
    load_company_profiles,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("seed_company_profiles")


def _join_mixed(items: list[Any], sep: str = ", ") -> str:
    """Склеить список в строку; dict-элементы (related_entities) — «name (type)»."""
    parts: list[str] = []
    for it in items or []:
        if isinstance(it, dict):
            name = it.get("name") or it.get("title") or ""
            extra = it.get("type") or it.get("position") or ""
            parts.append(f"{name} ({extra})".strip("() "))
        else:
            parts.append(str(it))
    return sep.join(p for p in parts if p)


def build_embedding_text(c: dict[str, Any]) -> str:
    """Склеить поля профиля компании в один текст для эмбеддинга (ТЗ, раздел 3.1).

    Поля читаются через .get() с безопасными значениями по умолчанию: в cp.json
    этого проекта нет колонок sector/sub_sector, а часть полей может отсутствовать.
    ``historical_patterns`` в этом проекте — обычный TEXT, допускаем str/list.
    """
    figures = "; ".join(
        f"{f.get('name', '')} ({f.get('position', '')}) — {f.get('mention_context', '')}".rstrip(" —")
        for f in c.get("key_figures", [])
    )
    triggers_data = c.get("news_triggers") or {}
    triggers = (
        f"Позитивные: {', '.join(triggers_data.get('positive', []))}. "
        f"Негативные: {', '.join(triggers_data.get('negative', []))}. "
        f"Нейтральные: {', '.join(triggers_data.get('neutral', []))}."
    )
    patterns = c.get("historical_patterns", "")
    patterns_str = "; ".join(patterns) if isinstance(patterns, list) else str(patterns or "")

    return f"""
Компания: {c.get('company_name', '')} (тикер {c.get('ticker', '')}, FIGI {c.get('figi', '')}).
Сектор: {c.get('sector', '')}, {c.get('sub_sector', '')}.
Описание: {c.get('description', '')}
Бизнес-модель: {c.get('business_model', '')}
Рыночная позиция: {c.get('market_position', '')}
Ключевые продукты: {', '.join(c.get('key_products', []))}.
Ключевые фигуры: {figures}.
Конкуренты: {_join_mixed(c.get('competitors', []))}.
Триггеры цены акций. {triggers}
Синонимы и упоминания: {_join_mixed(c.get('keywords_for_embedding', []))}.
Связанные сущности: {_join_mixed(c.get('related_entities', []))}.
Исторические паттерны реакции: {patterns_str}.
""".strip()


def enrich_with_embedding_text(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Добавить каждому профилю поле ``embedding_text`` (результат склейки).

    ``CompanyProfilesService.build_embed_text`` формирует собственный вариант
    склейки; здесь дополнительно кладём в профиль канонический текст по ТЗ —
    сервис использует его, если поле присутствует (см. _run_seed).
    """
    for prof in profiles:
        prof["embedding_text"] = build_embedding_text(prof)
    return profiles


async def _run_seed(json_path: str | None) -> dict[str, Any]:
    """Подключить БД/Ollama, выполнить ингест всех профилей, корректно закрыться."""
    settings = get_settings()
    database = Database(settings)
    embedder = OllamaEmbeddingClient(settings)
    try:
        await database.connect()
        service = CompanyProfilesService(settings, embedder, CompanyProfileRepository(database))

        profiles = load_company_profiles(settings, json_path)
        logger.info("Прочитано профилей из cp.json: %d", len(profiles))
        enrich_with_embedding_text(profiles)

        result = await service.ingest_from_profiles(profiles)
        logger.info(
            "Готово: total=%(total)d inserted=%(inserted)d updated=%(updated)d failed=%(failed)d",
            result,
        )
        return result
    finally:
        await embedder.aclose()
        await database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed company_profiles from cp.json with embeddings")
    parser.add_argument(
        "--json",
        default=None,
        help="Путь к cp.json (по умолчанию company_profiles/cp.json внутри сервиса)",
    )
    args = parser.parse_args()

    result = asyncio.run(_run_seed(args.json))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
