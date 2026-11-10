"""Базовый класс для алгоритмов алгоритмической торговли."""
import logging
from abc import abstractmethod
from typing import Any, Dict, List

from components.base import BaseComponent
from components.algorithms.params import AlgorithmDataRequest, AlgorithmParams
from schemas.market_data import MarketSnapshot

logger = logging.getLogger(__name__)


class BaseAlgorithm(BaseComponent[AlgorithmParams]):
    """
    Абстрактный базовый класс для всех алгоритмов торговли.
    
    Жизненный цикл алгоритма:
    1. get_data_request() - алгоритм запрашивает какие данные ему нужны
    2. Оркестратор получает эти данные через DataProvider
    3. execute() - алгоритм получает данные и выполняет расчеты
    4. Возвращает AlgorithmResult с расчетами
    
    Наследники должны реализовать:
    - get_name() - имя алгоритма
    - get_data_request() - какие данные нужны
    - execute() - логика расчетов
    """
    
    @abstractmethod
    def get_name(self) -> str:
        """
        Возвращает уникальное имя алгоритма.
        
        Используется для логирования и идентификации.
        """
        pass
    
    @abstractmethod
    def get_data_request(self, params: AlgorithmParams) -> AlgorithmDataRequest:
        """
        Запрашивает данные, необходимые для работы алгоритма.
        
        Args:
            params: Параметры запуска алгоритма
            
        Returns:
            AlgorithmDataRequest с указанием какие данные нужны
        """
        pass
    
    @abstractmethod
    async def execute(self, params: AlgorithmParams) -> Dict[str, Any]:
        """
        Выполняет расчеты алгоритма на основе полученных данных.
        
        Args:
            params: Параметры алгоритма с данными в custom_params
            
        Returns:
            Словарь с результатами расчетов алгоритма
        """
        pass
    
    def validate_data(self, snapshots: List[MarketSnapshot]) -> bool:
        """
        Проверяет корректность входных данных.
        
        Может быть переопределен в наследниках для специфичных проверок.
        
        Args:
            snapshots: Список снимков рынка
            
        Returns:
            True если данные валидны
        """
        if not snapshots:
            logger.warning(f"[{self.get_name()}] No data provided")
            return False
        return True
    
    def __str__(self) -> str:
        return f"Algorithm({self.get_name()})"
