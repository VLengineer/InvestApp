# Алгоритмическая торговля - Компонент алгоритмов

## Архитектура

Система построена на принципах SOLID и Clean Architecture:

### Компоненты

1. **BaseAlgorithm** (абстрактный класс)
   - Базовый класс для всех торговых алгоритмов
   - Метод `get_data_request()` - запрашивает необходимые данные
   - Метод `execute()` - выполняет расчеты и возвращает результат

2. **BaseDecisionMaker** (абстрактный класс)
   - Принимает результаты алгоритмов
   - Возвращает финальное торговое решение

3. **AlgorithmOrchestrator**
   - Координирует работу алгоритмов
   - Запрашивает данные для каждого алгоритма
   - Передает результаты в DecisionMaker
   - Возвращает TradingDecision

### Жизненный цикл

```
1. AlgorithmOrchestrator запускает каждый алгоритм:
   ├─ get_data_request() → какие данные нужны
   ├─ DataProvider → получение данных
   └─ execute() → расчеты алгоритма

2. Сбор всех AlgorithmResult

3. DecisionMaker:
   ├─ Анализ результатов алгоритмов
   ├─ Применение правил/логики
   └─ Возврат TradingDecision

4. (Опционально) Выполнение сделки
```

## Принципы SOLID

### Single Responsibility Principle (SRP)
- Каждый компонент отвечает за одну задачу
- Algorithm - только расчеты
- DecisionMaker - только принятие решений
- Orchestrator - только координация

### Open/Closed Principle (OCP)
- Можно добавлять новые алгоритмы без изменения оркестратора
- Можно добавлять новые DecisionMaker без изменения алгоритмов
- Система открыта для расширения, закрыта для модификации

### Dependency Inversion Principle (DIP)
- Orchestrator зависит от абстракций (BaseAlgorithm, BaseDecisionMaker)
- Конкретные реализации передаются через Dependency Injection
- Легко тестировать и заменять компоненты

## Структура файлов

```
components/
├── algorithms/
│   ├── base.py                      # Абстрактный класс BaseAlgorithm
│   ├── params.py                    # Параметры алгоритмов
│   ├── moving_average_crossover.py  # Пример: пересечение SMA
│   └── ml_trading.py                # Заготовка: ML алгоритм
├── decision_maker/
│   ├── base.py                      # Абстрактный класс BaseDecisionMaker
│   ├── params.py                    # Параметры DecisionMaker
│   └── rule_based.py                # Пример: правила
├── algorithm_orchestrator/
│   ├── orchestrator.py              # Оркестратор алгоритмов
│   └── params.py                    # Параметры оркестратора
└── base.py                          # BaseComponent

schemas/
├── market_data.py                   # Схемы рыночных данных
└── algorithm.py                     # Схемы алгоритмов и решений
```

## Как добавить новый алгоритм

1. Создайте новый класс, наследующий от `BaseAlgorithm`:

```python
from components.algorithms.base import BaseAlgorithm
from components.algorithms.params import AlgorithmDataRequest, AlgorithmParams
from schemas.algorithm import AlgorithmResult

class MyCustomAlgorithm(BaseAlgorithm):
    def get_name(self) -> str:
        return "MyCustomAlgorithm"
    
    def get_data_request(self, params: AlgorithmParams) -> AlgorithmDataRequest:
        return AlgorithmDataRequest(
            instrument_id=params.instrument_id,
            interval=params.interval,
            limit=100,
        )
    
    async def execute(self, params: AlgorithmParams) -> dict:
        # Ваша логика расчетов
        return AlgorithmResult(
            algorithm_name=self.get_name(),
            signal=SignalType.BUY,
            confidence=DecisionConfidence.HIGH,
            metrics={"custom_metric": 123},
        )
```

2. Добавьте алгоритм в оркестратор:

```python
algorithms = [
    MovingAverageCrossoverAlgorithm(),
    MyCustomAlgorithm(),  # Новый алгоритм
]

orchestrator = AlgorithmOrchestrator(
    algorithms=algorithms,
    decision_maker=decision_maker,
    data_provider=data_provider,
)
```

## Как добавить новый DecisionMaker

1. Создайте новый класс, наследующий от `BaseDecisionMaker`:

```python
from components.decision_maker.base import BaseDecisionMaker
from components.decision_maker.params import DecisionMakerParams
from schemas.algorithm import TradingDecision

class MyDecisionMaker(BaseDecisionMaker):
    def get_name(self) -> str:
        return "MyDecisionMaker"
    
    async def execute(self, params: DecisionMakerParams) -> TradingDecision:
        # Ваша логика принятия решений
        return TradingDecision(
            instrument_id=params.instrument_id,
            action=SignalType.BUY,
            confidence=DecisionConfidence.HIGH,
            reason="Custom logic",
        )
```

2. Используйте в оркестраторе:

```python
decision_maker = MyDecisionMaker()
orchestrator = AlgorithmOrchestrator(
    algorithms=algorithms,
    decision_maker=decision_maker,
    data_provider=data_provider,
)
```

## Примеры использования

См. `example_algorithm_usage.py` для полного примера запуска.

## Расширение системы

### ML алгоритмы
- `MLTradingAlgorithm` - заготовка для ML модели
- Метод `train()` для обучения на исторических данных
- Feature engineering в `_extract_features()`
- Prediction в `_predict()`

### Future enhancements
- Добавить компонент для исполнения сделок (TradeExecutor)
- Добавить компонент для управления рисками (RiskManager)
- Добавить компонент для backtesting
- Добавить компонент для мониторинга и алертов

## Тестирование

Каждый компонент можно тестировать изолированно:

```python
# Тест алгоритма
algorithm = MovingAverageCrossoverAlgorithm()
result = await algorithm.execute(params)
assert result.signal == SignalType.BUY

# Тест DecisionMaker
decision_maker = RuleBasedDecisionMaker()
decision = await decision_maker.execute(params)
assert decision.action == SignalType.BUY

# Тест Orchestrator с моками
orchestrator = AlgorithmOrchestrator(
    algorithms=[mock_algorithm],
    decision_maker=mock_decision_maker,
    data_provider=mock_data_provider,
)
```
