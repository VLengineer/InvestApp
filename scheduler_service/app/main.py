"""Точка входа FastAPI-приложения микросервиса scheduler_service.

Собирает всё вместе (паттерн python_test/app/main.py):
  * конфигурация — app/core/config.py (только env/.env через pydantic-settings);
  * логирование с маскированием секретов — app/core/logging.py;
  * HTTP-эндпоинты — app/api/routes/ (единый api_router);
  * фоновый воркер — app/workers/scheduler_worker.py, запускается из lifespan
    через asyncio.create_task и корректно отменяется при shutdown.

Запуск: uvicorn app.main:app --host 0.0.0.0 --port 8200
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.api.routes import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.database import Database
from app.db.repository import SchedulerRepository
from app.workers.scheduler_worker import SchedulerWorker

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """startup/shutdown: подключение БД, идемпотентная схема, старт/остановка воркера."""
    database = Database(settings)
    await database.connect()
    # В проде таблицы создаёт init_db/04_init_scheduler.sql; здесь тот же DDL
    # IF NOT EXISTS — чтобы локальный запуск без docker работал из коробки.
    await database.ensure_schema()

    repository = SchedulerRepository(database)
    worker = SchedulerWorker(settings, repository)
    await worker.start()

    # Объекты живущие в app.state — источник для зависимостей app/api/deps.py.
    app.state.database = database
    app.state.repository = repository
    app.state.worker = worker

    logger.info("%s v%s запущен (env=%s)", settings.app_name, settings.app_version, settings.environment)
    try:
        yield
    finally:
        # Порядок важен: сначала остановить цикл воркера, потом закрывать пул БД.
        await worker.stop()
        await database.close()


app = FastAPI(
    title="scheduler_service (циклический опрос n8n: очередь задач в PostgreSQL + callback)",
    version=settings.app_version,
    debug=False,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url="/openapi.json" if not settings.is_production else None,
    lifespan=lifespan,
)

app.include_router(api_router)
