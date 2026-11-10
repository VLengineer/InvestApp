"""AlgorithmOrchestrator для координации работы алгоритмов и принятия решений."""
import logging
import time
from typing import List

from components.base import BaseComponent
from components.algorithms.base import BaseAlgorithm
from components.algorithms.params import AlgorithmParams
from components.decision_maker.base import BaseDecisionMaker
from components.decision_maker.params import DecisionMakerParams
from components.algorithm_orchestrator.params import AlgorithmOrchestratorParams
from components.data_provider.provider import DataProvider
from schemas.algorithm import AlgorithmResult, TradingDecision, SignalType
from schemas.market_data import MarketSnapshot

logger = logging.getLogger(__name__)


class AlgorithmOrchestrator(BaseComponent[AlgorithmOrchestratorParams]):
    """
    Оркестратор для координации работы алгоритмов торговли.
    
    Жизненный цикл:
    1. Для каждого алгоритма:
       a. Запрашивает какие данные нужны (get_data_request)
       b. Получает данные через DataProvider
       c. Передает данные в алгоритм
       d. Получает AlgorithmResult
    2. Собирает все результаты алгоритмов
    3. Передает результаты в DecisionMaker
    4. Получает финальное TradingDecision
    5. (Опционально) Выполняет сделку
    
    Архитектура следует принципам SOLID:
    - Single Responsibility: каждый компонент отвечает за свою задачу
    - Open/Closed: можно добавлять новые алгоритмы без изменения оркестратора
    - Dependency Inversion: оркестратор зависит от абстракций (BaseAlgorithm, BaseDecisionMaker)
    """
    
    def __init__(
        self,
        algorithms: List[BaseAlgorithm],
        decision_maker: BaseDecisionMaker,
        data_provider: DataProvider,
    ):
        """
        Args:
            algorithms: Список алгоритмов для выполнения
            decision_maker: Компонент для принятия решений
            data_provider: Провайдер данных
        """
        self.algorithms = algorithms
        self.decision_maker = decision_maker
        self.data_provider = data_provider
    
    async def execute(self, params: AlgorithmOrchestratorParams) -> TradingDecision:
        """
        Выполняет полный цикл: алгоритмы → решение → (опционально) сделка.
        
        Args:
            params: Параметры оркестратора
            
        Returns:
            TradingDecision с финальным решением
        """
        logger.info(f"Starting algorithm orchestration for {len(self.algorithms)} algorithms")
        
        # Шаг 1: Выполняем все алгоритмы
        algorithm_results = await self._execute_algorithms(params)
        
        if not algorithm_results:
            logger.warning("No algorithm results obtained")
            return self._create_empty_decision(params)
        
        # Шаг 2: Передаем результаты в DecisionMaker
        decision = await self._make_decision(params, algorithm_results)
        
        # Шаг 3: (Опционально) Выполняем сделку
        if params.execute_trades and decision.action != SignalType.HOLD:
            await self._execute_trade(decision)
        
        logger.info(
            f"Orchestration complete. Decision: {decision.action} "
            f"(confidence: {decision.confidence})"
        )
        
        return decision
    
    async def _execute_algorithms(
        self,
        params: AlgorithmOrchestratorParams,
    ) -> List[AlgorithmResult]:
        """Выполняет все алгоритмы и собирает результаты."""
        results = []
        
        for algorithm in self.algorithms:
            try:
                result = await self._execute_single_algorithm(algorithm, params)
                if result:
                    results.append(result)
            except Exception as e:
                logger.error(f"Error executing algorithm {algorithm.get_name()}: {e}")
        
        return results
    
    async def _execute_single_algorithm(
        self,
        algorithm: BaseAlgorithm,
        orchestrator_params: AlgorithmOrchestratorParams,
    ) -> AlgorithmResult | None:
        """
        Выполняет один алгоритм:
        1. Запрашивает данные
        2. Получает данные
        3. Выполняет расчеты
        """
        start_time = time.time()
        
        # Используем первый instrument_id из параметров
        if not orchestrator_params.algorithm_params:
            logger.error(f"No algorithm params provided for {algorithm.get_name()}")
            return None
        
        algo_params = orchestrator_params.algorithm_params[0]
        
        # Шаг 1: Запрашиваем данные
        data_request = algorithm.get_data_request(algo_params)
        logger.info(
            f"[{algorithm.get_name()}] Requesting data: "
            f"{data_request.instrument_id}, interval={data_request.interval}, "
            f"limit={data_request.limit}"
        )
        
        # Шаг 2: Получаем данные
        # В реальной реализации здесь будет вызов DataProvider с параметрами из data_request
        # Пока используем заглушку - получаем данные из orchestrator_params
        snapshots = self._get_mock_data(data_request)
        
        if not snapshots:
            logger.warning(f"[{algorithm.get_name()}] No data received")
            return None
        
        # Шаг 3: Выполняем алгоритм
        algo_params_with_data = AlgorithmParams(
            instrument_id=algo_params.instrument_id,
            interval=algo_params.interval,
            limit=algo_params.limit,
            custom_params={"snapshots": snapshots},
        )
        
        result_dict = await algorithm.execute(algo_params_with_data)
        
        # Конвертируем в AlgorithmResult если нужно
        if isinstance(result_dict, dict):
            # Если алгоритм вернул словарь, предполагаем что это уже AlgorithmResult
            result = AlgorithmResult(**result_dict)
        else:
            result = result_dict
        
        execution_time = (time.time() - start_time) * 1000
        logger.info(
            f"[{algorithm.get_name()}] Execution time: {execution_time:.2f}ms, "
            f"Signal: {result.signal}"
        )
        
        return result
    
    async def _make_decision(
        self,
        orchestrator_params: AlgorithmOrchestratorParams,
        algorithm_results: List[AlgorithmResult],
    ) -> TradingDecision:
        """Передает результаты алгоритмов в DecisionMaker."""
        decision_params = DecisionMakerParams(
            instrument_id=orchestrator_params.algorithm_params[0].instrument_id,
            algorithm_results=algorithm_results,
            current_price=orchestrator_params.current_price,
            open_position_quantity=orchestrator_params.open_position_quantity,
            max_position_size=orchestrator_params.max_position_size,
            custom_context=orchestrator_params.custom_context,
        )
        
        return await self.decision_maker.execute(decision_params)
    
    async def _execute_trade(self, decision: TradingDecision) -> None:
        """
        Выполняет торговую операцию.
        
        В реальной реализации здесь будет вызов торгового API.
        """
        logger.info(
            f"Executing trade: {decision.action} {decision.quantity} "
            f"of {decision.instrument_id} at {decision.price}"
        )
        
        # Заглушка для реальной торговли
        # В реальной реализации:
        # - Вызов TInvest API для размещения ордера
        # - Логирование сделки
        # - Обновление позиции
        # - Установка стоп-лоссов и тейк-профитов
    
    def _get_mock_data(self, data_request) -> List[MarketSnapshot]:
        """
        Получает мок-данные для демонстрации.
        
        В реальной реализации здесь будет вызов DataProvider.
        """
        # Заглушка: возвращаем пустой список
        # В реальной реализации:
        # return await self.data_provider.execute(data_request)
        return []
    
    def _create_empty_decision(self, params: AlgorithmOrchestratorParams) -> TradingDecision:
        """Создает пустое решение HOLD."""
        instrument_id = (
            params.algorithm_params[0].instrument_id
            if params.algorithm_params
            else "UNKNOWN"
        )
        
        return TradingDecision(
            instrument_id=instrument_id,
            action=SignalType.HOLD,
            confidence="LOW",
            reason="No algorithm results",
            metadata={"orchestrator": "AlgorithmOrchestrator"},
        )
    
    async def close(self) -> None:
        """Закрывает ресурсы."""
        # Если есть ресурсы для закрытия
        pass
