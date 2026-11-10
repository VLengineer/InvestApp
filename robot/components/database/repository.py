"""Репозиторий для работы с БД."""
import logging
from typing import List

import asyncpg

from components.base import BaseComponent
from components.database.params import DatabaseParams
from components.database.schema import SCHEMA_DDL, INSERT_SQL, INSERT_COLUMNS
from components.database.row_mapper import snapshot_to_db_row
from schemas.market_data import MarketSnapshot

logger = logging.getLogger(__name__)


class DatabaseRepository(BaseComponent[DatabaseParams]):
    """Компонент для сохранения данных в PostgreSQL."""
    
    def __init__(
        self,
        database_url: str,
        min_pool_size: int = 1,
        max_pool_size: int = 4,
    ):
        self.database_url = database_url
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        self._pool: asyncpg.Pool = None
    
    async def _get_pool(self) -> asyncpg.Pool:
        """Ленивая инициализация пула соединений."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self.database_url,
                min_size=self.min_pool_size,
                max_size=self.max_pool_size,
            )
        return self._pool
    
    async def close(self) -> None:
        """Закрывает пул соединений."""
        if self._pool:
            await self._pool.close()
            self._pool = None
    
    async def ensure_schema(self) -> None:
        """Создаёт таблицу и индексы, если их нет."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(SCHEMA_DDL)
        logger.info("Database schema ensured")
    
    async def execute(self, params: DatabaseParams) -> int:
        """
        Сохраняет снимки в БД.
        
        Note: Этот метод требует предварительной установки snapshots через set_snapshots().
        Лучше использовать save_snapshots() напрямую.
        """
        raise NotImplementedError("Use save_snapshots() instead")
    
    async def save_snapshots(
        self,
        snapshots: List[MarketSnapshot],
        params: DatabaseParams,
    ) -> int:
        """Batch INSERT снимков в БД. Возвращает количество вставленных строк."""
        if not snapshots:
            logger.warning("No snapshots to save")
            return 0
        
        pool = await self._get_pool()
        
        rows = [snapshot_to_db_row(s, figi=params.figi) for s in snapshots]
        values = [
            tuple(r[col] for col in INSERT_COLUMNS)
            for r in rows
        ]
        
        async with pool.acquire() as conn:
            await conn.executemany(INSERT_SQL, values)
        
        logger.info("Saved %d rows to robot_market_data (figi=%s)", len(values), params.figi)
        return len(values)
