"""Параметры для компонента принятия решений."""
from dataclasses import dataclass, field
from typing import List, Optional

from schemas.algorithm import AlgorithmResult


@dataclass
class DecisionMakerParams:
    """
    Параметры для принятия торгового решения.
    
    Содержит результаты одного или нескольких алгоритмов,
    на основе которых принимается решение.
    """
    instrument_id: str
    algorithm_results: List[AlgorithmResult] = field(default_factory=list)
    current_price: Optional[float] = None
    open_position_quantity: int = 0
    max_position_size: int = 100
    custom_context: Optional[dict] = None
