"""Выдача JWT-токенов (эндпоинт доступен только держателю admin-ключа).

Идея: секрет JWT никогда не покидает сервис. Внешние клиенты (n8n, веб-приложения)
получают короткоживущий токен по X-API-Key и дальше ходят с
``Authorization: Bearer <token>``.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.core.config import get_settings
from app.core.security import ALL_SCOPES, issue_token
from app.schemas.api_schemas import TokenRequest, TokenResponse


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
    summary="Выдать JWT по admin-ключу",
    description=(
        "Тело: `{ \"subject\": \"n8n\", \"scopes\": [\"rag:read\", \"rag:index\"] }`.\n\n"
        "Доступен только запросам с заголовком `X-API-Key: <ADMIN_API_KEY>`.\n"
        "Разрешённые scopes: " + ", ".join(s.value for s in ALL_SCOPES) + "."
    ),
)
async def create_token(body: TokenRequest) -> TokenResponse:
    settings = get_settings()
    ttl = body.ttl_seconds or settings.access_token_ttl_s
    token = issue_token(subject=body.subject, scopes=list(body.scopes), settings=settings, ttl_seconds=ttl)
    return TokenResponse(access_token=token, expires_in=ttl, scopes=list(body.scopes))
