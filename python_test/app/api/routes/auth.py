"""Выдача JWT-токенов (эндпоинт доступен только держателю admin-ключа).

Идея: секрет JWT никогда не покидает сервис. Внешние клиенты (n8n, веб-приложения)
получают токен по X-API-Key и дальше ходят с ``Authorization: Bearer <token>``.

По умолчанию выдаются БЕССРОЧНЫЕ токены (без claim ``exp``): TTL берётся из env
``ACCESS_TOKEN_TTL_S`` (0 = бессрочный), либо явно указывается в запросе
(``"ttl_seconds": 3600`` — токен на час, ``0``/``null`` — бессрочный).
"""

from __future__ import annotations

import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.core.config import get_settings
from app.core.diagnostics import explain_token_failure, peek_token
from app.core.security import ALL_SCOPES, _extract_scopes, issue_token
from app.schemas.api_schemas import TokenRequest, TokenResponse, VerifyTokenRequest, VerifyTokenResponse


def require_admin_key(
    x_api_key: Annotated[str | None, Header(description="Машинный admin-ключ (env: ADMIN_API_KEY)")] = None,
) -> None:
    """Constant-time сверка с ADMIN_API_KEY; если ключ не настроен — доступ запрещён."""
    settings = get_settings()
    expected = settings.admin_api_key
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Выдача токенов отключена: переменная окружения ADMIN_API_KEY не задана",
        )
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется корректный заголовок 'X-API-Key' (admin)",
            headers={"WWW-Authenticate": "ApiKey"},
        )


router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(require_admin_key)])


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Выдать JWT по admin-ключу (по умолчанию — бессрочный)",
    description=(
        "Тело: `{ \"subject\": \"n8n\", \"scopes\": [\"rag:read\", \"rag:index\"] }`.\n\n"
        "`ttl_seconds`: `null` или `0` — токен без срока действия (по умолчанию); `3600` — на 1 час.\n\n"
        "Доступен только запросам с заголовком `X-API-Key: <ADMIN_API_KEY>`.\n"
        "Разрешённые scopes: " + ", ".join(s.value for s in ALL_SCOPES) + "."
    ),
)
async def create_token(body: TokenRequest) -> TokenResponse:
    settings = get_settings()
    ttl = body.ttl_seconds if body.ttl_seconds is not None else settings.access_token_ttl_s
    token = issue_token(subject=body.subject, scopes=list(body.scopes), settings=settings, ttl_seconds=ttl or None)
    return TokenResponse(access_token=token, expires_in=ttl or None, scopes=list(body.scopes))


@router.post(
    "/verify-token",
    response_model=VerifyTokenResponse,
    summary="Диагностика: почему сервер отвергает конкретный JWT",
    description=(
        "Полезно, когда Swagger пишет «Недействительный или просроченный токен доступа», "
        "а причину не видно (в 401 она намеренно не раскрывается).\n\n"
        "Вставьте тот же токен, который подставили в поле `Authorize` — эндпоинт покажет "
        "`header`/`payload` токена, ожидаемые сервером `iss`/`aud` и **список конкретных причин** отказа:\n\n"
        "* подпись не совпадает → токен выпущен с другим `JWT_SECRET_KEY`;\n"
        "* нет claim `iss`/`aud` → у сервера заданы `JWT_ISSUER`/`JWT_AUDIENCE`, добавьте их при выпуске;\n"
        "* нет `iat`/`sub` или просрочен `exp`.\n\n"
        "Секреты и API-ключи в ответе не возвращаются. Доступ только с `X-API-Key: <ADMIN_API_KEY>`."
    ),
)
async def verify_token(body: VerifyTokenRequest) -> VerifyTokenResponse:
    """Подробный разбор входящего токена (для отладки авторизации)."""
    settings = get_settings()
    token = body.token.strip().removeprefix("Bearer ").removeprefix("bearer ").strip()
    header: dict[str, Any] = {}
    payload: dict[str, Any] = {}
    try:
        header, payload = peek_token(token)
    except ValueError:
        pass  # причина будет в reasons
    reasons = explain_token_failure(token, settings)
    return VerifyTokenResponse(
        valid=not reasons,
        header=header,
        payload=payload,
        expected_iss=settings.jwt_issuer,
        expected_aud=settings.jwt_audience,
        scopes=[s.value for s in _extract_scopes(payload)] if payload else [],
        reasons=reasons,
    )
