"""Зависимости FastAPI: общие объекты (настройки, хранилище, индексатор) и JWT-защита."""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

bearer_scheme = HTTPBearer(auto_error=False)


def get_jwt_secret(settings: Annotated[Settings, Depends(get_settings)]) -> str | None:
    return settings.jwt_secret


async def require_jwt(
    settings: Annotated[Settings, Depends(get_settings)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> dict:
    """Проверяет `Authorization: Bearer <JWT HS256>`.

    Если JWT_SECRET не задан — авторизация отключена (удобно для локального запуска/CLI).
    """
    if not settings.jwt_secret:
        return {"sub": "anonymous", "auth_disabled": True}
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется заголовок Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(
            credentials.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Токен просрочен")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Некорректный токен")
    return payload


def make_token(secret: str, algorithm: str = "HS256", ttl_hours: int = 24, sub: str = "rag-client") -> str:
    """Утилита для генерации токена (используется в тестах и README)."""
    import datetime as dt

    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode(
        {"sub": sub, "iat": now, "exp": now + dt.timedelta(hours=ttl_hours)},
        secret,
        algorithm=algorithm,
    )
