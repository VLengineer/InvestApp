"""Параметры для AlgorithmOrchestrator."""
from dataclasses import dataclass, field
from typing import List, Optional

from components.algorithms.params import AlgorithmParams
from components.decision_maker.params import DecisionMakerParams


@dataclass
class AlgorithmOrchestratorParams:
    """
    Параметры для запуска AlgorithmOrchestrator.
    
    Содержит параметры для алгоритмов и контекст для принятия решений.
    """
    algorithm_params: List[AlgorithmParams] = field(default_factory=list)
    current_price: Optional[float] = None
    open_position_quantity: int = 0
    max_position_size: int = 100
    execute_trades: bool = False  # Флаг для тестирования: выполнять ли реальные сделки
    custom_context: Optional[dict] = None
