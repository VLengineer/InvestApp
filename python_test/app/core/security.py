"""Безопасность: проверка JWT (HS256) и ролевая модель.

Требования к токену:
  * подпись HMAC-SHA256 секретом из env ``JWT_SECRET_KEY``;
  * обязательные claims: ``exp``, ``iat``, ``sub``, ``iss``, ``aud``;
  * ``scope``/``role`` должен содержать нужный scopes (admin для записи/индексации).

Секрет никогда не читается из запроса и не попадает в логи.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWTError

from app.core.config import Settings, get_settings

ALGORITHM_WHITELIST = ["HS256"]  # явный whitelist: исключаем alg=none / подмену алгоритма


class Scope(StrEnum):
    READ = "rag:read"
    INDEX = "rag:index"
    ADMIN = "rag:admin"


ALL_SCOPES: tuple[Scope, ...] = (Scope.READ, Scope.INDEX, Scope.ADMIN)


@dataclass(frozen=True, slots=True)
class Principal:
    """Аутентифицированный субъект (пользователь или сервис)."""

    subject: str
    scopes: frozenset[Scope] = field(default_factory=frozenset)
    issuer: str | None = None

    def has(self, scope: Scope) -> bool:
        return scope in self.scopes or Scope.ADMIN in self.scopes


def decode_token(token: str, settings: Settings) -> dict:
    """Проверяет подпись, алгоритм, срок действия и iss/aud токена."""
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=ALGORITHM_WHITELIST,
            issuer=settings.jwt_issuer or None,
            audience=settings.jwt_audience or None,
            options={
                "require": ["exp", "iat", "sub"],
                "verify_exp": True,
                "verify_iat": True,
                "leeway": 0,
            },
        )
    except PyJWTError as exc:  # единое сообщение — не раскрываем причину атакующему
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или просроченный токен доступа",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _extract_scopes(payload: dict) -> frozenset[Scope]:
    raw: list[str] = []
    for key in ("scope", "scopes"):
        value = payload.get(key)
        if isinstance(value, str):
            raw.extend(value.split())
        elif isinstance(value, (list, tuple)):
            raw.extend(str(v) for v in value)
    role = payload.get("role")
    if isinstance(role, str):
        raw.append(role)
    known = {s.value: s for s in ALL_SCOPES}
    return frozenset(known[item] for item in raw if item in known)


async def get_principal(
    authorization: Annotated[str | None, Header(description="Bearer <JWT>")] = None,
    x_api_key: Annotated[str | None, Header(description="Машинный доступ (n8n)")] = None,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    """Два канала доступа: JWT (основной) и X-API-Key (для внутренних сервисов)."""
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Ожидается заголовок 'Authorization: Bearer <token>'",
                headers={"WWW-Authenticate": "Bearer"},
            )
        payload = decode_token(token.strip(), settings)
        return Principal(
            subject=str(payload.get("sub")),
            scopes=_extract_scopes(payload),
            issuer=payload.get("iss"),
        )

    if x_api_key and settings.api_keys:
        # constant-time сравнение со ВСЕМИ ключами — без раннего выхода
        matched = False
        for key in settings.api_keys:
            if secrets.compare_digest(x_api_key, key):
                matched = True
        if matched:
            return Principal(subject="api-key-client", scopes=frozenset({Scope.INDEX, Scope.READ}))

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Требуется авторизация (JWT или API-ключ)",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_scope(scope: Scope):
    """Фабрика зависимостей: RBAC на уровне эндпоинта."""

    async def _dep(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if not principal.has(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Для операции требуется scope '{scope.value}'",
            )
        return principal

    return _dep


# --------------------------- Утилита для генерации токенов -------------------
def issue_token(
    *,
    subject: str,
    scopes: list[str],
    settings: Settings,
    ttl_seconds: int = 3600,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "scope": " ".join(scopes),
        "iss": settings.jwt_issuer or settings.app_name,
        "aud": settings.jwt_audience or settings.app_name,
        "iat": now,
        "exp": now.timestamp() + ttl_seconds,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
