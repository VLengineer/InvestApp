"""
Пример использования AlgorithmOrchestrator.

Демонстрирует полный цикл:
1. Создание алгоритмов
2. Создание DecisionMaker
3. Запуск AlgorithmOrchestrator
4. Получение торгового решения
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from common.logging import setup_logging
from common.http_client import HTTPClient
from config import Config
from components.algorithms.moving_average_crossover import MovingAverageCrossoverAlgorithm
from components.algorithms.ml_trading import MLTradingAlgorithm
from components.algorithms.params import AlgorithmParams, CandleInterval
from components.decision_maker.rule_based import RuleBasedDecisionMaker
from components.algorithm_orchestrator.orchestrator import AlgorithmOrchestrator
from components.algorithm_orchestrator.params import AlgorithmOrchestratorParams
from components.data_provider.provider import DataProvider


async def main() -> None:
    """Пример запуска алгоритмической торговли."""
    logger = setup_logging(logging.INFO)

    # Инициализация HTTP клиента и DataProvider
    http_client = HTTPClient(
        base_url=Config.BASE_URL,
        token=Config.TINVEST_TOKEN,
        max_concurrent_requests=Config.MAX_CONCURRENT_REQUESTS,
    )
    data_provider = DataProvider(
        http_client=http_client,
        max_concurrent_requests=Config.MAX_CONCURRENT_REQUESTS,
    )

    # Создание алгоритмов
    algorithms = [
        MovingAverageCrossoverAlgorithm(short_period=10, long_period=30),
        MLTradingAlgorithm(confidence_threshold=0.6, lookback_period=100),
        # Можно добавить новые алгоритмы без изменения оркестратора (Open/Closed Principle)
    ]

    # Создание DecisionMaker
    decision_maker = RuleBasedDecisionMaker(
        min_confidence="MEDIUM",
        require_unanimous=False,  # Простое большинство
    )

    # Создание AlgorithmOrchestrator
    # Dependency Injection: оркестратор зависит от абстракций (DIP)
    orchestrator = AlgorithmOrchestrator(
        algorithms=algorithms,
        decision_maker=decision_maker,
        data_provider=data_provider,
    )

    try:
        # Параметры для каждого алгоритма
        algorithm_params = [
            AlgorithmParams(
                instrument_id="BBG004730N88",  # Сбербанк
                interval=CandleInterval.FIFTEEN_MINUTES,
                limit=100,
            ),
        ]

        # Параметры оркестратора
        orchestrator_params = AlgorithmOrchestratorParams(
            algorithm_params=algorithm_params,
            current_price=295.89,
            open_position_quantity=0,
            max_position_size=100,
            execute_trades=False,  # Тестовый режим
        )

        # Запуск полного цикла
        decision = await orchestrator.execute(orchestrator_params)

        # Вывод результата
        logger.info("=" * 60)
        logger.info("TRADING DECISION")
        logger.info("=" * 60)
        logger.info(f"Instrument: {decision.instrument_id}")
        logger.info(f"Action:     {decision.action}")
        logger.info(f"Confidence: {decision.confidence}")
        logger.info(f"Price:      {decision.price}")
        logger.info(f"Quantity:   {decision.quantity}")
        logger.info(f"Reason:     {decision.reason}")
        logger.info("=" * 60)

        # Информация по каждому алгоритму
        for result in decision.algorithm_results:
            logger.info(
                f"  Algorithm: {result.algorithm_name} → "
                f"Signal: {result.signal}, Confidence: {result.confidence}"
            )

    finally:
        await orchestrator.close()


if __name__ == "__main__":
    asyncio.run(main())
