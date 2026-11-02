"""Пакет микросервиса «Анализатор новостей» (news_analyzer).

Код каждого нового микросервиса живёт в СВОЕЙ папке внутри python_test
(см. python_test/MICROSERVICES.md). Эндпоинты регистрируются отдельным
файлом в app/api/routes/, который импортирует сервисы из этого пакета.

Структура пакета:
    schemas.py    — pydantic-модели (контракт API);
    repository.py — работа с таблицей market_news_ml_dataset (asyncpg);
    service.py    — бизнес-логика (валидация ts, сохранение записи).
"""

from app.news_analyzer.schemas import NewsAnalyzeRequest, NewsAnalyzeResponse
from app.news_analyzer.service import NewsAnalyzerService

__all__ = ["NewsAnalyzeRequest", "NewsAnalyzeResponse", "NewsAnalyzerService"]
