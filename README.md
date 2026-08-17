# News Market Analyzer

Система автоматизированного анализа финансовых новостей с оценкой их влияния на рынок на основе LLM и RAG.

## 📋 Описание

**News Market Analyzer** анализирует новости из T-Invest API, классифицирует их, находит методологический контекст в базе знаний и генерирует:
- Текстовый аналитический отчёт
- 7 количественных метрик влияния на рынок (сентимент, волатильность, объёмы, отраслевое влияние, кратко/среднесрочные эффекты, уверенность)

## 🏗️ Архитектура

```
src/
├── config/              # Конфигурация через .env
├── domain/              # Доменные модели
│   └── models.py        # NewsItem, ImpactScores, Candle, Timeframe
├── orchestration/       # Бизнес-логика
│   ├── analysis.py      # Движок анализа (4 этапа)
│   ├── news_orchestrator.py  # Сбор и анализ новостей
│   ├── market_orchestrator.py # Главный пайплайн
│   └── prompt_builder.py     # Шаблоны промптов для LLM
├── providers/           # Внешние сервисы
│   ├── llm/             # LLM-провайдеры (GPTunnel, Ollama)
│   │   ├── base.py      # Абстрактный интерфейс
│   │   ├── gptunnel.py  # GPTunnel API
│   │   └── ollama.py    # Локальная Ollama
│   ├── rag/             # RAG-компоненты
│   │   ├── rag_provider.py  # Основной RAG-провайдер
│   │   ├── embedding.py     # Векторизация текста
│   │   ├── vector_db.py     # FAISS для поиска
│   │   └── document_db.py   # SQLite для документов
│   ├── tinvest/         # T-Invest API клиент
│   │   ├── base.py      # Абстрактный интерфейс
│   │   └── client.py    # Реализация клиента
│   └── db/              # Базы данных
│       └── sqlite_db.py # SQLite обёртка
└── tests/               # Тесты
    ├── test_analysis.py
    ├── test_rag.py
    ├── test_llm.py
    └── test_orchestrators.py
```

## ⚙️ Установка

### Требования
- Python 3.9+
- API ключи: T-Invest, GPTunnel (опционально)
- Docker (опционально, для Ollama)

### Шаг 1: Клонирование
```bash
git clone <repository-url>
cd news-market-analyzer
```

### Шаг 2: Создание виртуального окружения
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

### Шаг 3: Установка зависимостей
```bash
pip install -r requirements.txt
```

### Шаг 4: Настройка переменных окружения
Создайте файл `.env` в корне проекта:

```env
# T-Invest API
TINVEST_API_KEY=your_tinvest_api_key
TINVEST_SANDBOX=true

# LLM Provider (выберите один)
LLM_PROVIDER=gptunnel  # или ollama
GPTUNNEL_API_KEY=your_gptunnel_api_key
GPTUNNEL_MODEL=qwen3.8

# Ollama (если используется локально)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# RAG Configuration
EMBEDDING_PROVIDER=sentence-transformers
EMBEDDING_MODEL=all-MiniLM-L6-v2
RAG_TOP_K=3

# Database
DATABASE_PATH=data/news_analyzer.db
```

### Шаг 5: Запуск Ollama (опционально)
Если используете локальную Ollama:
```bash
docker run -d -p 11434:11434 --name ollama ollama/ollama
docker exec -it ollama ollama pull llama3
```

## 🚀 Использование

### Быстрый старт
```bash
python src/main.py
```

### Программный вызов
```python
import asyncio
from src.orchestration.market_orchestrator import NewsMarketOrchestrator

async def main():
    orchestrator = NewsMarketOrchestrator()
    
    # Анализ последних новостей
    results = await orchestrator.analyze_latest_news(limit=5)
    
    for result in results:
        print(f"Новость: {result.news.headline}")
        print(f"Сентимент: {result.scores.market_sentiment}")
        print(f"Анализ: {result.analysis_text[:200]}...")
        print("-" * 80)

asyncio.run(main())
```

### Анализ конкретной новости
```python
from src.domain.models import NewsItem
from src.orchestration.analysis import NewsAnalysisEngine

async def analyze_single_news():
    news = NewsItem(
        headline="ЦБ повысил ключевую ставку до 16%",
        text="Банк России принял решение повысить ключевую ставку...",
        source="T-Invest",
        published_at="2024-01-15T10:00:00Z"
    )
    
    engine = NewsAnalysisEngine()
    result = await engine.analyze_news(news)
    
    print(result.scores)

asyncio.run(analyze_single_news())
```

## 🔍 Как это работает

### Пайплайн анализа (4 этапа)

1. **Классификация**
   - LLM определяет тип новости: positive/negative/neutral/macroeconomic/corporate/regulatory
   - Пример: "Повышение ставки" → macroeconomic, negative

2. **Генерация RAG-запросов**
   - Создаются поисковые запросы для нахождения методологического контекста
   - Пример: "влияние повышения ставки на рынок акций", "методика оценки макроэкономических новостей"

3. **Поиск контекста (RAG)**
   - Векторизация запросов через embedding модель
   - Поиск ближайших документов в FAISS
   - Извлечение оригинальных текстов из SQLite

4. **Генерация анализа и оценок**
   - LLM создаёт развёрнутый аналитический отчёт с опорой на найденные методики
   - Генерация 7 численных метрик в формате JSON:
     - `market_sentiment` (-1.0 до 1.0)
     - `volatility_impact` (-1.0 до 1.0)
     - `volume_impact` (-1.0 до 1.0)
     - `sector_impact` (-1.0 до 1.0)
     - `short_term_effect` (-1.0 до 1.0)
     - `medium_term_effect` (-1.0 до 1.0)
     - `confidence_score` (0.0 до 1.0)

## 🧪 Тестирование

### Запуск всех тестов
```bash
pytest tests/ -v
```

### Запуск по модулям
```bash
# Тесты RAG
pytest tests/test_rag.py -v

# Тесты анализа
pytest tests/test_analysis.py -v

# Тесты оркестраторов
pytest tests/test_orchestrators.py -v

# Тесты LLM провайдеров
pytest tests/test_llm.py -v
```

### Покрытие тестами
- ✅ RAG: добавление документов, поиск, векторизация
- ✅ Анализ: классификация, генерация запросов, парсинг оценок
- ✅ Оркестраторы: интеграционные сценарии
- ✅ LLM: мокирование ответов, обработка ошибок

## 📊 Доменные модели

### NewsItem
```python
{
    "headline": "Заголовок новости",
    "text": "Полный текст новости",
    "source": "Источник",
    "published_at": "2024-01-15T10:00:00Z"
}
```

### ImpactScores
```python
{
    "market_sentiment": 0.75,      # Общий сентимент
    "volatility_impact": 0.60,     # Влияние на волатильность
    "volume_impact": 0.45,         # Влияние на объём
    "sector_impact": -0.30,        # Отраслевое влияние
    "short_term_effect": 0.80,     # Краткосрочный эффект
    "medium_term_effect": 0.50,    # Среднесрочный эффект
    "confidence_score": 0.85       # Уверенность анализа
}
```

## 🔧 Конфигурация LLM провайдеров

### GPTunnel (облачный)
```env
LLM_PROVIDER=gptunnel
GPTUNNEL_API_KEY=your_key
GPTUNNEL_MODEL=qwen3.8
```

### Ollama (локальный)
```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
```

## 🗄️ База знаний RAG

### Добавление документов
```python
from src.providers.rag.rag_provider import RAGProvider

rag = RAGProvider()

documents = [
    {
        "content": "Методика оценки влияния макроэкономических новостей...",
        "metadata": {"type": "methodology", "topic": "macroeconomics"}
    }
]

await rag.add_documents(documents)
```

### Поиск контекста
```python
results = await rag.search(
    query="влияние повышения ставки на рынок",
    top_k=3
)

for doc in results:
    print(doc.content)
    print(doc.metadata)
```

## 📝 Лицензия

MIT License

## 🤝 Вклад в проект

1. Fork репозитория
2. Создайте ветку (`git checkout -b feature/amazing-feature`)
3. Commit изменений (`git commit -m 'Add amazing feature'`)
4. Push в ветку (`git push origin feature/amazing-feature`)
5. Откройте Pull Request

## 📞 Контакты

Вопросы и предложения: откройте Issue в репозитории.
