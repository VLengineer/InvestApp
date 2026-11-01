"""Пакет микросервиса «Анализатор новостей» (news_analyzer).

Код каждого нового микросервиса живёт в СВОЕЙ папке внутри python_test
(см. python_test/MICROSERVICES.md). Эндпоинты регистрируются отдельным
файлом в app/api/routes/, который импортирует сервисы из этого пакета.

Структура пакета:
    schemas.py  — pydantic-модели (контракт API);
    client.py   — HTTP-клиент вебхука n8n (URL берётся из env N8N_BASE_URL + N8N_NEWS_WEBHOOK_PATH);
    service.py  — бизнес-логика (пересылка новости на n8n/news_analizer).

ВАЖНО: микросервис сам НЕ пишет в БД — сохранением в market_news_ml_dataset
занимается сценарий n8n, вызванный вебхуком.
"""

from news_analyzer.client import N8nForwardError, N8nWebhookClient
from news_analyzer.schemas import NewsAnalyzeRequest, NewsAnalyzeResponse
from news_analyzer.service import NewsAnalyzerService

__all__ = [
    "N8nForwardError",
    "N8nWebhookClient",
    "NewsAnalyzeRequest",
    "NewsAnalyzeResponse",
    "NewsAnalyzerService",
]
