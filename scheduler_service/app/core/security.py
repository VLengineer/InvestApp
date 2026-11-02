"""Безопасность scheduler_service: проверка JWT (HS256) — копия паттерна python_test.

Схема доступа проекта упрощена: ОДИН бессрочный JWT-токен на всё
(подпись HMAC-SHA256 секретом JWT_SECRET_KEY, обязательные claims iat/sub).
Здесь используется только базовая проверка токена (admin-эндпоинты start/stop);
RBAC по scope не нужен — все права даёт один универсальный токен.

Секрет никогда не читается из запроса и не попадает в логи.
"""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError

from app.core.config import Settings, get_settings

ALGORITHM_WHITELIST = ["HS256"]  # явный whitelist: исключаем alg=none / подмену алгоритма


def decode_token(token: str, settings: Settings) -> dict:
    """Проверяет подпись, алгоритм и (если настроено) iss/aud токена.

    ``exp`` обязателен только при ``JWT_REQUIRE_EXP=true``; по умолчанию
    бессрочные токены (без ``exp``) принимаются. Если ``exp`` присутствует —
    он валидируется как обычно. Двухпроходная схема (сначала без verify_iss/aud,
    затем с ними) повторяет python_test: если сервер не настраивал iss/aud,
    но claim есть в токене — ожидаем значение app_name.
    """
    expected_iss = settings.jwt_issuer or None
    expected_aud = settings.jwt_audience or None
    try:
        header_claims = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=ALGORITHM_WHITELIST,
            options={
                "verify_signature": True,
                "verify_exp": False,
                "verify_iat": False,
                "verify_iss": False,
                "verify_aud": False,
                "require": ["iat", "sub"] + (["exp"] if settings.jwt_require_exp else []),
                "leeway": settings.jwt_leeway_s,
            },
        )
        if expected_iss is None and "iss" in header_claims:
            expected_iss = settings.app_name
        if expected_aud is None and "aud" in header_claims:
            expected_aud = settings.app_name
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=ALGORITHM_WHITELIST,
            issuer=expected_iss,
            audience=expected_aud,
            options={
                "require": ["iat", "sub"] + (["exp"] if settings.jwt_require_exp else []),
                "verify_exp": True,
                "verify_iat": True,
                "leeway": settings.jwt_leeway_s,
            },
        )
    except PyJWTError as exc:  # единое сообщение — не раскрываем причину атакующему
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или просроченный токен доступа",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# HTTPBearer нужен для кнопки Authorize в Swagger UI; auto_error=False —
# сообщения об ошибках формируем сами (единые для всего сервиса).
bearer_scheme = HTTPBearer(auto_error=False, description="JWT из get_token.py")


async def get_current_principal(
    settings: Annotated[Settings, Depends(get_settings)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ] = None,
) -> str:
    """Единственный канал доступа к admin-эндпоинтам: JWT в заголовке Authorization."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Требуется заголовок 'Authorization: Bearer <token>' "
                "(токен генерируется скриптом get_token.py)."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )
    if (credentials.scheme or "").strip().lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ожидается заголовок 'Authorization: Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials.strip(), settings)
    return str(payload.get("sub"))


PrincipalDep = Annotated[str, Depends(get_current_principal)]
