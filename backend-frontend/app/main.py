"""Точка входа FastAPI-приложения микросервиса backend-frontend (BFF для Vue-фронта).

Собирает всё вместе (паттерн scheduler_service/app/main.py):
  * конфигурация — app/core/config.py (только env/.env через pydantic-settings);
  * логирование с маскированием секретов — app/core/logging.py;
  * REST-эндпоинты — app/api/routes/ (единый api_router);
  * WebSocket real-time — app/routers/websocket.py;
  * фоновый цикл рассылки новых данных — MarketService.start()/stop() из lifespan.

Запуск: uvicorn app.main:app --host 0.0.0.0 --port 8300
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.database import Database
from app.repositories.market_repository import MarketRepository
from app.routers import websocket as ws_router
from app.services.market_service import MarketService

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """startup/shutdown: подключение БД, сборка сервисов, старт/остановка real-time цикла."""
    database = Database(settings)
    await database.connect()

    repository = MarketRepository(database)
    market_service = MarketService(settings, repository)
    await market_service.start()

    # Объекты, живущие в app.state — источник для зависимостей app/api/deps.py.
    app.state.database = database
    app.state.market_service = market_service

    logger.info("%s v%s запущен (env=%s)", settings.app_name, settings.app_version, settings.environment)
    try:
        yield
    finally:
        # Порядок важен: сначала остановить цикл рассылки, потом закрывать пул БД.
        await market_service.stop()
        await database.close()


app = FastAPI(
    title="backend-frontend (BFF для Vue-дашборда: рынок + новости + real-time WS)",
    version=settings.app_version,
    debug=False,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url="/openapi.json" if not settings.is_production else None,
    lifespan=lifespan,
)

# CORS только для фронта (требование ТЗ «Безопасность»): origin'ы настраиваются env'ом.
if settings.cors_allow_origins.strip() == "*":
    allow_origins = ["*"]
else:
    allow_origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,  # авторизации на фронте нет — cookies не пускаем
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

# REST: /api/market/*, /live, /ready
app.include_router(api_router)
# WebSocket: /ws/market-updates
app.include_router(ws_router.router)
