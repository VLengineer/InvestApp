"""Пример конкретного алгоритма: Strategy based on Moving Average Crossover."""
import logging
from typing import Any, Dict, List

from components.algorithms.base import BaseAlgorithm
from components.algorithms.params import AlgorithmDataRequest, AlgorithmParams, CandleInterval
from schemas.market_data import MarketSnapshot
from schemas.algorithm import AlgorithmResult, SignalType, DecisionConfidence

logger = logging.getLogger(__name__)


class MovingAverageCrossoverAlgorithm(BaseAlgorithm):
    """
    Пример алгоритма: пересечение скользящих средних.
    
    Стратегия:
    - Если короткая SMA пересекает длинную SMA снизу вверх → BUY
    - Если короткая SMA пересекает длинную SMA сверху вниз → SELL
    - Иначе → HOLD
    
    Это заглушка для демонстрации архитектуры.
    """
    
    def __init__(
        self,
        short_period: int = 10,
        long_period: int = 30,
    ):
        """
        Args:
            short_period: Период короткой скользящей средней
            long_period: Период длинной скользящей средней
        """
        self.short_period = short_period
        self.long_period = long_period
    
    def get_name(self) -> str:
        return "MovingAverageCrossover"
    
    def get_data_request(self, params: AlgorithmParams) -> AlgorithmDataRequest:
        """
        Запрашивает данные свечей для расчета скользящих средних.
        
        Нужно минимум long_period свечей для расчета.
        """
        return AlgorithmDataRequest(
            instrument_id=params.instrument_id,
            interval=params.interval,
            limit=max(self.long_period + 10, params.limit),  # Запас данных
        )
    
    async def execute(self, params: AlgorithmParams) -> Dict[str, Any]:
        """
        Выполняет расчет пересечения скользящих средних.
        
        В params.custom_params должны быть данные:
        - snapshots: List[MarketSnapshot]
        """
        snapshots: List[MarketSnapshot] = params.custom_params.get("snapshots", [])
        
        if not self.validate_data(snapshots):
            return AlgorithmResult(
                algorithm_name=self.get_name(),
                signal=SignalType.HOLD,
                confidence=DecisionConfidence.LOW,
                metrics={"error": "No data available"},
            )
        
        # Извлекаем цены закрытия
        close_prices = []
        for snapshot in snapshots:
            if snapshot.candle:
                close_prices.append(snapshot.candle.close.to_float())
        
        if len(close_prices) < self.long_period:
            return AlgorithmResult(
                algorithm_name=self.get_name(),
                signal=SignalType.HOLD,
                confidence=DecisionConfidence.LOW,
                metrics={"error": f"Not enough data: {len(close_prices)} < {self.long_period}"},
            )
        
        # Рассчитываем скользящие средние
        short_sma = self._calculate_sma(close_prices, self.short_period)
        long_sma = self._calculate_sma(close_prices, self.long_period)
        
        # Определяем сигнал
        signal = self._determine_signal(short_sma, long_sma)
        
        logger.info(
            f"[{self.get_name()}] Short SMA: {short_sma[-1]:.2f}, "
            f"Long SMA: {long_sma[-1]:.2f}, Signal: {signal}"
        )
        
        return AlgorithmResult(
            algorithm_name=self.get_name(),
            signal=signal,
            confidence=DecisionConfidence.MEDIUM,
            metrics={
                "short_sma": short_sma[-1],
                "long_sma": long_sma[-1],
                "short_period": self.short_period,
                "long_period": self.long_period,
            },
            raw_calculations={
                "short_sma_series": short_sma,
                "long_sma_series": long_sma,
            },
        )
    
    def _calculate_sma(self, prices: List[float], period: int) -> List[float]:
        """Рассчитывает простую скользящую среднюю."""
        sma_values = []
        for i in range(period, len(prices) + 1):
            window = prices[i - period:i]
            sma_values.append(sum(window) / period)
        return sma_values
    
    def _determine_signal(self, short_sma: List[float], long_sma: List[float]) -> SignalType:
        """
        Определяет торговый сигнал на основе пересечения SMA.
        
        Упрощенная логика для демонстрации.
        """
        if len(short_sma) < 2 or len(long_sma) < 2:
            return SignalType.HOLD
        
        # Текущее и предыдущее значение
        short_current = short_sma[-1]
        short_prev = short_sma[-2]
        long_current = long_sma[-1]
        long_prev = long_sma[-2]
        
        # Пересечение снизу вверх (BUY)
        if short_prev <= long_prev and short_current > long_current:
            return SignalType.BUY
        
        # Пересечение сверху вниз (SELL)
        if short_prev >= long_prev and short_current < long_current:
            return SignalType.SELL
        
        # Тренд вверх
        if short_current > long_current:
            return SignalType.HOLD
        
        # Тренд вниз
        return SignalType.HOLD
