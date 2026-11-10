"""Схемы для результатов алгоритмов и торговых решений."""
from enum import StrEnum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class SignalType(StrEnum):
    """Тип сигнала от алгоритма."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE_POSITION = "CLOSE_POSITION"


class DecisionConfidence(StrEnum):
    """Уверенность в решении."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AlgorithmResult(BaseModel):
    """
    Результат выполнения алгоритма.
    
    Содержит расчеты и метрики алгоритма для последующей обработки.
    """
    algorithm_name: str
    signal: SignalType
    confidence: DecisionConfidence = DecisionConfidence.MEDIUM
    metrics: Dict[str, Any] = Field(default_factory=dict)
    raw_calculations: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        use_enum_values = True


class TradingDecision(BaseModel):
    """
    Торговое решение на основе результатов алгоритмов.
    
    Принимается DecisionMaker на основе одного или нескольких AlgorithmResult.
    """
    instrument_id: str
    action: SignalType
    confidence: DecisionConfidence
    price: Optional[float] = None
    quantity: Optional[int] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reason: str = ""
    algorithm_results: list[AlgorithmResult] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        use_enum_values = True


class AlgorithmExecutionResult(BaseModel):
    """
    Полный результат выполнения алгоритма с данными.
    
    Используется оркестратором для передачи между компонентами.
    """
    algorithm_name: str
    data_request: Dict[str, Any]
    algorithm_result: AlgorithmResult
    execution_time_ms: Optional[float] = None
    error: Optional[str] = None
    
    class Config:
        use_enum_values = True
