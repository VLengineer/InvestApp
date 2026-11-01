"""Слой представления: FastAPI-приложение, middleware безопасности, обработка ошибок."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.api.routes import api_router
from app.container import Container
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, mask

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Базовые заголовки безопасности + request id (безопасно и для HTTP-деплоя в LAN)."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001, D401
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        
        # 1. ИСКЛЮЧЕНИЕ: Не применяем строгий CSP к документации Swagger/ReDoc
        # Им необходимы внешние CDN, inline-скрипты и доступ к openapi.json
        if request.url.path in ["/docs", "/redoc", "/openapi.json"]:
            response = await call_next(request)
            response.headers["X-Request-Id"] = request_id
            # Остальные строгие заголовки не добавляем, чтобы не ломать UI
            return response

        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001 - логируем с полным стеком, наружу — generic 500
            logger.exception("Необработанная ошибка запроса %s %s", request.method, request.url.path)
            response = JSONResponse(
                status_code=500,
                content={"code": "internal_error", "message": "Внутренняя ошибка сервера",
                         "details": {"request_id": request_id}},
            )
        
        # 2. Строгие заголовки безопасности только для основных API-маршрутов
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-Id"] = request_id
        
        logger.info(
            "%s %s -> %s (%.1f ms)",
            request.method, mask(str(request.url.path)), response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response
def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="RAG Knowledge Base Indexer",
        version=settings.app_version,
        description=(
            "Индексация «общих» JSON из knowledge_base через Ollama с сохранением "
            "документов и векторов в PostgreSQL+pgvector. Доступ по одному JWT-токену.\n\n"
            "**Схема простая**: админ-ключей и X-API-Key больше нет. Один бессрочный токен "
            "(без claim `exp`) подходит для всех эндпоинтов и всех клиентов (Swagger, n8n). "
            "Сгенерировать его: `python get_token.py --secret \"$JWT_SECRET_KEY\"`.\n\n"
            "**Как пользоваться Swagger:** нажмите `Authorize` и вставьте токен "
            "(только сам токен, без слова `Bearer`)."
        ),
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        # схема security описана вручную в _custom_openapi (только JWT Bearer)
    )
    app.state.settings = settings
    app.state.container: Container | None = None

    app.add_middleware(SecurityHeadersMiddleware)

    @app.on_event("startup")
    async def _startup() -> None:
        container = Container.build(app.state.settings)
        await container.startup()
        app.state.container = container

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        container: Container | None = app.state.container
        if container is not None:
            await container.shutdown()

    # ------------------------- обработка доменных ошибок ----------------------
    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError) -> JSONResponse:
        logger.warning("Доменная ошибка [%s]: %s", exc.code, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, "details": exc.details},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        safe: list[dict[str, Any]] = [
            {"loc": [str(p) for p in err.get("loc", [])], "msg": str(err.get("msg", ""))}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"code": "validation_error", "message": "Ошибка валидации запроса",
                     "details": {"errors": safe}},
        )

    app.include_router(api_router)

    # ------------------------- Swagger «как положено» ------------------------
    def _custom_openapi() -> dict[str, Any]:
        """OpenAPI со стандартной схемой security: только JWT Bearer (один токен на всё)."""
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        schema.setdefault("components", {})["securitySchemes"] = {
            "BearerJWT": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": (
                    "Единый бессрочный JWT (HS256). Сгенерировать: "
                    "python get_token.py --secret \"<JWT_SECRET_KEY>\". "
                    "Вставлять в Swagger — только сам токен, без 'Bearer '."
                ),
            },
        }
        # Все защищённые эндпоинты — один канал: Bearer JWT; /live и /ready — открытые
        open_paths = {"/live", "/ready"}
        for path, item in schema.get("paths", {}).items():
            if path in open_paths:
                continue
            for operation in item.values():
                if isinstance(operation, dict):
                    operation["security"] = [{"BearerJWT": []}]
        schema["x-error-format"] = {"code": "string", "message": "string", "details": {}}
        app.openapi_schema = schema
        return schema

    app.openapi = _custom_openapi
    return app


# Экземпляр приложения для uvicorn (app.main:app) — без него uvicorn не находит ASGI-приложение
app = create_app()
