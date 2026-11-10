"""
Точка входа приложения.

Компонентная архитектура:
- data_provider: загрузка данных из TInvest API → MarketSnapshot
- database: сохранение MarketSnapshot → PostgreSQL
- orchestrator: пакетная загрузка и сохранение
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path для корректных импортов
sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from common.logging import setup_logging
from common.http_client import HTTPClient
from components.data_provider.provider import DataProvider
from components.data_provider.params import DataProviderParams
from components.database.repository import DatabaseRepository
from components.orchestrator.orchestrator import Orchestrator
from components.orchestrator.params import OrchestratorParams


async def main() -> None:
    """Точка входа: собирает датасет и сохраняет в PostgreSQL."""
    logger = setup_logging(logging.INFO)
    
    if not Config.TINVEST_TOKEN:
        logger.error("TINVEST_TOKEN is not set. Set it in .env or environment.")
        return
    
    # Инициализация компонентов
    http_client = HTTPClient(
        base_url=Config.BASE_URL,
        token=Config.TINVEST_TOKEN,
        max_concurrent_requests=Config.MAX_CONCURRENT_REQUESTS,
    )
    
    data_provider = DataProvider(
        http_client=http_client,
        max_concurrent_requests=Config.MAX_CONCURRENT_REQUESTS,
    )
    
    database_repository = DatabaseRepository(
        database_url=Config.DATABASE_URL,
    )
    
    orchestrator = Orchestrator(
        data_provider=data_provider,
        database_repository=database_repository,
    )
    
    try:
        # Получаем FIGI из окружения
        figi = os.getenv("FIGI", "BBG004730N88")
        
        # Формируем параметры для загрузки
        # Можно добавить несколько инструментов для пакетной обработки
        dp_params = [
            DataProviderParams(
                instrument_id=figi,
                from_ts="2026-11-10T00:00:00Z",
                to_ts="2026-11-10T23:59:59Z",
            ),
            # Добавьте дополнительные инструменты здесь:
            # DataProviderParams(
            #     instrument_id="BBG000B9XRY4",
            #     from_ts="2026-11-10T00:00:00Z",
            #     to_ts="2026-11-10T23:59:59Z",
            # ),
        ]
        
        params = OrchestratorParams(
            data_provider_params=dp_params,
            batch_size=100,
        )
        
        # Запуск оркестратора
        total_saved = await orchestrator.execute(params)
        logger.info(f"Done. Total saved: {total_saved} rows")
        
    finally:
        await orchestrator.close()


if __name__ == "__main__":
    asyncio.run(main())
