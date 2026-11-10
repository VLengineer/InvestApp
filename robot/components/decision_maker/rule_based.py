"""Пример DecisionMaker: RuleBasedDecisionMaker."""
import logging

from components.decision_maker.base import BaseDecisionMaker
from components.decision_maker.params import DecisionMakerParams
from schemas.algorithm import TradingDecision, SignalType, DecisionConfidence

logger = logging.getLogger(__name__)


class RuleBasedDecisionMaker(BaseDecisionMaker):
    """
    Пример DecisionMaker: принятие решений на основе правил.
    
    Упрощенная логика для демонстрации архитектуры:
    - Если все алгоритмы согласны → выполняем сделку
    - Если есть разногласия → HOLD
    - Учитываем текущую позицию для избежания дублирования
    
    Это заглушка для демонстрации архитектуры.
    """
    
    def __init__(
        self,
        min_confidence: DecisionConfidence = DecisionConfidence.MEDIUM,
        require_unanimous: bool = True,
    ):
        """
        Args:
            min_confidence: Минимальная уверенность для принятия решения
            require_unanimous: Требовать единогласия всех алгоритмов
        """
        self.min_confidence = min_confidence
        self.require_unanimous = require_unanimous
    
    def get_name(self) -> str:
        return "RuleBasedDecisionMaker"
    
    async def execute(self, params: DecisionMakerParams) -> TradingDecision:
        """
        Принимает решение на основе результатов алгоритмов.
        
        Логика:
        1. Проверяем наличие результатов
        2. Анализируем сигналы и уверенность
        3. Проверяем текущую позицию
        4. Возвращаем финальное решение
        """
        if not params.algorithm_results:
            logger.warning(f"[{self.get_name()}] No algorithm results provided")
            return self._create_hold_decision(params, "No algorithm results")
        
        # Собираем сигналы
        signals = [result.signal for result in params.algorithm_results]
        confidences = [result.confidence for result in params.algorithm_results]
        
        # Проверяем уверенность
        confidence_order = {
            DecisionConfidence.LOW: 0,
            DecisionConfidence.MEDIUM: 1,
            DecisionConfidence.HIGH: 2,
        }
        
        min_confidence_level = confidence_order[self.min_confidence]
        valid_results = [
            result for result in params.algorithm_results
            if confidence_order[result.confidence] >= min_confidence_level
        ]
        
        if not valid_results:
            return self._create_hold_decision(params, "Insufficient confidence")
        
        # Анализируем сигналы
        buy_count = sum(1 for r in valid_results if r.signal == SignalType.BUY)
        sell_count = sum(1 for r in valid_results if r.signal == SignalType.SELL)
        hold_count = sum(1 for r in valid_results if r.signal == SignalType.HOLD)
        
        total = len(valid_results)
        
        # Определяем финальное решение
        if self.require_unanimous:
            # Все должны согласиться
            if buy_count == total:
                final_signal = SignalType.BUY
            elif sell_count == total:
                final_signal = SignalType.SELL
            else:
                return self._create_hold_decision(params, "No unanimous decision")
        else:
            # Простое большинство
            if buy_count > sell_count and buy_count > hold_count:
                final_signal = SignalType.BUY
            elif sell_count > buy_count and sell_count > hold_count:
                final_signal = SignalType.SELL
            else:
                return self._create_hold_decision(params, "No clear majority")
        
        # Проверяем текущую позицию
        if final_signal == SignalType.BUY and params.open_position_quantity > 0:
            return self._create_hold_decision(params, "Already in long position")
        
        if final_signal == SignalType.SELL and params.open_position_quantity <= 0:
            return self._create_hold_decision(params, "No position to sell")
        
        # Формируем решение
        avg_confidence = self._calculate_avg_confidence(confidences)
        
        decision = TradingDecision(
            instrument_id=params.instrument_id,
            action=final_signal,
            confidence=avg_confidence,
            price=params.current_price,
            quantity=self._calculate_quantity(params, final_signal),
            reason=f"Consensus: {buy_count} BUY, {sell_count} SELL, {hold_count} HOLD",
            algorithm_results=params.algorithm_results,
            metadata={
                "decision_maker": self.get_name(),
                "total_algorithms": total,
                "buy_count": buy_count,
                "sell_count": sell_count,
                "hold_count": hold_count,
            },
        )
        
        logger.info(
            f"[{self.get_name()}] Decision: {final_signal} for {params.instrument_id} "
            f"(confidence: {avg_confidence})"
        )
        
        return decision
    
    def _create_hold_decision(
        self,
        params: DecisionMakerParams,
        reason: str,
    ) -> TradingDecision:
        """Создает решение HOLD."""
        logger.info(f"[{self.get_name()}] HOLD: {reason}")
        return TradingDecision(
            instrument_id=params.instrument_id,
            action=SignalType.HOLD,
            confidence=DecisionConfidence.LOW,
            reason=reason,
            algorithm_results=params.algorithm_results,
            metadata={"decision_maker": self.get_name()},
        )
    
    def _calculate_avg_confidence(self, confidences: list[DecisionConfidence]) -> DecisionConfidence:
        """Рассчитывает среднюю уверенность."""
        confidence_values = {
            DecisionConfidence.LOW: 1,
            DecisionConfidence.MEDIUM: 2,
            DecisionConfidence.HIGH: 3,
        }
        
        avg_value = sum(confidence_values[c] for c in confidences) / len(confidences)
        
        if avg_value >= 2.5:
            return DecisionConfidence.HIGH
        elif avg_value >= 1.5:
            return DecisionConfidence.MEDIUM
        else:
            return DecisionConfidence.LOW
    
    def _calculate_quantity(self, params: DecisionMakerParams, signal: SignalType) -> int:
        """
        Рассчитывает количество для сделки.
        
        Упрощенная логика для демонстрации.
        """
        # В реальной реализации здесь будет расчет на основе:
        # - размера позиции
        # - риска
        # - волатильности
        # - размера счета
        
        if signal == SignalType.BUY:
            available_capacity = params.max_position_size - params.open_position_quantity
            return min(10, available_capacity)  # Заглушка: покупаем 10
        
        elif signal == SignalType.SELL:
            return abs(params.open_position_quantity)  # Продаем всю позицию
        
        return 0
