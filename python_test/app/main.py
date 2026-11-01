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
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001 - логируем с полным стеком, наружу — generic 500
            logger.exception("Необработанная ошибка запроса %s %s", request.method, request.url.path)
            response = JSONResponse(
                status_code=500,
                content={"code": "internal_error", "message": "Внутренняя ошибка сервера",
                         "details": {"request_id": request_id}},
            )
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
            "Индексация «общих» JSON из knowledge_base через Ollama (nomic-embed-text) "
            "с сохранением документов и векторов в PostgreSQL+pgvector. Доступ по JWT.\n\n"
            "**Как пользоваться Swagger:** нажмите `Authorize` и введите токен "
            "(сначала получите его через `POST /auth/token` с admin-ключом в X-API-Key) "
            "или используйте машинный ключ в поле API_KEY_BEARER (вставляется как X-API-Key)."
        ),
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        # схемы security описаны вручную в _custom_openapi (JWT Bearer + X-API-Key)
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
        """OpenAPI со стандартными схемами security: JWT Bearer и X-API-Key."""
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
                "description": "JWT из POST /auth/token (Authorization: Bearer <token>)",
            },
            "ApiKeyHeader": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
                "description": "Машинный ключ из env API_KEYS (для n8n и внутренних сервисов)",
            },
        }
        # /auth/token — только admin-ключ; остальные защищённые эндпоинты — JWT или API-ключ
        auth_paths = [p for p in schema.get("paths", {}) if p.startswith("/auth/")]
        open_paths = {"/live", "/ready"}
        for path, item in schema.get("paths", {}).items():
            if path in open_paths:
                continue
            for operation in item.values():
                if isinstance(operation, dict):
                    operation["security"] = (
                        [{"ApiKeyHeader": []}] if path in auth_paths else [{"BearerJWT": []}, {"ApiKeyHeader": []}]
                    )
        schema["x-error-format"] = {"code": "string", "message": "string", "details": {}}
        app.openapi_schema = schema
        return schema

    app.openapi = _custom_openapi
    return app


# Экземпляр приложения для uvicorn (app.main:app) — без него uvicorn не находит ASGI-приложение
app = create_app()
