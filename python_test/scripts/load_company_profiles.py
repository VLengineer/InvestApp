#!/usr/bin/env python3
"""Скрипт загрузки company_profiles/cp.json в таблицу company_profiles.

Делает ровно то же, что POST /company-profiles/ingest, но из командной строки:
  python scripts/load_company_profiles.py [--json path/to/cp.json]

1. Читает все профили из cp.json.
2. Для каждого формирует склеенный текст по приоритету полей:
   company_name+ticker+figi, description, business_model, keywords_for_embedding,
   related_entities, news_triggers (positive+negative+neutral), key_products,
   key_figures (имена+должности), market_position, historical_patterns,
   target_audience, geography, competitors, regulatory_dependencies,
   technology_stack, financial_metrics_of_interest, correlation_factors.
3. Получает вектор (768 dim) через Ollama:
   hf.co/unsloth/embeddinggemma-2-GGUF:UD-Q6_K_XL
4. Upsert-ит строку в PostgreSQL (pgvector) в таблицу company_profiles.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# делаем пакет app импортируемым при запуске скрипта напрямую
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.clients.ollama import OllamaEmbeddingClient  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.database import Database  # noqa: E402
from app.repositories.company_profile_repository import CompanyProfileRepository  # noqa: E402
from app.services.company_profiles_service import CompanyProfilesService  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("load_company_profiles")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        default=str(ROOT / "company_profiles" / "cp.json"),
        help="Путь к cp.json (по умолчанию company_profiles/cp.json)",
    )
    args = parser.parse_args()

    result = asyncio.run(_run_ingest(args.json))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["failed"] == 0 else 1


async def _run_ingest(json_path: str) -> dict:
    """Собрать граф зависимостей (как в Container), выполнить ингест, корректно закрыться."""
    settings = get_settings()
    database = Database(settings)
    embedder = OllamaEmbeddingClient(settings)
    try:
        await database.connect()
        service = CompanyProfilesService(settings, embedder, CompanyProfileRepository(database))
        return await service.ingest(json_path)
    finally:
        await embedder.aclose()
        await database.close()


if __name__ == "__main__":
    raise SystemExit(main())
