"""Базовый класс для компонента принятия торговых решений."""
import logging
from abc import abstractmethod

from components.base import BaseComponent
from components.decision_maker.params import DecisionMakerParams
from schemas.algorithm import TradingDecision

logger = logging.getLogger(__name__)


class BaseDecisionMaker(BaseComponent[DecisionMakerParams]):
    """
    Абстрактный базовый класс для принятия торговых решений.
    
    Получает результаты алгоритмов и принимает финальное решение
    о покупке, продаже или удержании позиции.
    
    Жизненный цикл:
    1. Оркестратор собирает результаты алгоритмов
    2. Передаёт их в DecisionMaker через execute()
    3. DecisionMaker возвращает TradingDecision
    
    Наследники должны реализовать:
    - get_name() - имя decision maker
    - execute() - логика принятия решения
    
    Примеры наследников:
    - RuleBasedDecisionMaker — решение на основе правил
    - MLDecisionMaker — решение на основе ML-модели
    - ConsensusDecisionMaker — голосование нескольких алгоритмов
    """
    
    @abstractmethod
    def get_name(self) -> str:
        """
        Возвращает уникальное имя decision maker.
        
        Используется для логирования и идентификации.
        """
        pass
    
    @abstractmethod
    async def execute(self, params: DecisionMakerParams) -> TradingDecision:
        """
        Принимает торговое решение на основе результатов алгоритмов.
        
        Args:
            params: Параметры с результатами алгоритмов и контекстом
            
        Returns:
            TradingDecision с финальным решением
        """
        pass
    
    def __str__(self) -> str:
        return f"DecisionMaker({self.get_name()})"
