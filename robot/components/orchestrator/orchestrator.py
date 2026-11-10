"""Оркестратор для пакетной обработки данных."""
import logging
from typing import List

from components.base import BaseComponent
from components.data_provider.provider import DataProvider
from components.data_provider.params import DataProviderParams
from components.database.repository import DatabaseRepository
from components.database.params import DatabaseParams
from components.orchestrator.params import OrchestratorParams
from schemas.market_data import MarketSnapshot

logger = logging.getLogger(__name__)


class Orchestrator(BaseComponent[OrchestratorParams]):
    """
    Оркестратор для пакетной загрузки и сохранения данных.
    
    Обрабатывает данные пакетами:
    1. Загружает данные для каждого инструмента
    2. Сохраняет в БД батчами
    """
    
    def __init__(
        self,
        data_provider: DataProvider,
        database_repository: DatabaseRepository,
    ):
        self.data_provider = data_provider
        self.database_repository = database_repository
    
    async def execute(self, params: OrchestratorParams) -> int:
        """
        Выполняет пакетную загрузку и сохранение данных.
        
        Returns:
            Общее количество сохранённых строк
        """
        total_saved = 0
        
        # Обеспечиваем схему БД
        await self.database_repository.ensure_schema()
        
        # Обрабатываем каждый инструмент
        for dp_params in params.data_provider_params:
            logger.info(f"Processing {dp_params.instrument_id}")
            
            # Загружаем данные
            snapshots = await self.data_provider.execute(dp_params)
            
            if not snapshots:
                logger.warning(f"No data for {dp_params.instrument_id}")
                continue
            
            # Сохраняем батчами
            saved = await self._save_in_batches(
                snapshots,
                dp_params.instrument_id,
                params.batch_size,
            )
            total_saved += saved
        
        logger.info(f"Total saved: {total_saved} rows")
        return total_saved
    
    async def _save_in_batches(
        self,
        snapshots: List[MarketSnapshot],
        figi: str,
        batch_size: int,
    ) -> int:
        """Сохраняет снимки батчами."""
        total_saved = 0
        
        for i in range(0, len(snapshots), batch_size):
            batch = snapshots[i:i + batch_size]
            db_params = DatabaseParams(figi=figi)
            saved = await self.database_repository.save_snapshots(batch, db_params)
            total_saved += saved
            logger.debug(f"Saved batch {i // batch_size + 1}: {saved} rows")
        
        return total_saved
    
    async def close(self) -> None:
        """Закрывает ресурсы."""
        await self.database_repository.close()
