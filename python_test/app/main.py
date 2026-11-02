"""Точка входа FastAPI-приложения микросервиса python_test.

Собирает всё вместе:
  * конфигурация — app/core/config.py (только из переменных окружения / .env);
  * граф зависимостей (Composition Root) — app/core/container.py;
  * все HTTP-эндпоинты — app/api/routes/ (единый api_router);
  * логирование с маскированием секретов — app/core/logging.py.

Запуск: uvicorn app.main:app --host 0.0.0.0 --port 8100
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import api_router
from app.core.config import get_settings
from app.core.container import Container
from app.core.exceptions import AppError
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware:
    """ASGI-middleware: базовые security-заголовки на каждый ответ.

    Простая реализация без BaseHTTPMiddleware, чтобы не ломать streaming и
    фоновые задачи (IndexingService запускается через asyncio.create_task).
    """

    _HEADERS = (
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
    )

    def __init__(self, app) -> None:  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def _send(message) -> None:  # noqa: ANN001
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                for key, value in self._HEADERS:
                    headers.append((key, value))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, _send)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """startup/shutdown: подключение БД, проверка Ollama, корректное закрытие."""
    container = Container.build(settings)
    await container.startup()
    app.state.container = container
    logger.info("%s v%s запущен (env=%s)", settings.app_name, settings.app_version, settings.environment)
    try:
        yield
    finally:
        await container.shutdown()


app = FastAPI(
    title="python_test RAG microservice (rag / news_analyzer / indicators / company_profiles)",
    version=settings.app_version,
    debug=False,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url="/openapi.json" if not settings.is_production else None,
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)

# Все роутеры микросервиса собираются в app/api/routes/__init__.py
app.include_router(api_router)


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """Доменные исключения -> единый JSON-формат ошибок API."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, "details": exc.details},
    )
