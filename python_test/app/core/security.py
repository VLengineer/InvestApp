"""Безопасность: проверка JWT (HS256) и ролевая модель.

Упрощённая схема доступа — ОДИН токен на всё:
  * подпись HMAC-SHA256 секретом из env ``JWT_SECRET_KEY``;
  * обязательные claims: ``iat``, ``sub``;
  * срок действия НЕ обязателен: токены без ``exp`` («бессрочные») валидны,
    а ``exp`` при наличии всё равно проверяется (env ``JWT_REQUIRE_EXP=false``);
  * ``iss``/``aud`` проверяются только если заданы соответствующие env-переменные;
  * если в токене нет ``scope``/``role`` — считаются ВСЕ права (токен универсальный).

Никаких отдельных admin-ключей и X-API-Key больше нет: все каналы (Swagger, n8n,
скрипты) используют один и тот же JWT в заголовке ``Authorization: Bearer <token>``.

Секрет никогда не читается из запроса и не попадает в логи.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
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
    """Проверяет подпись, алгоритм и (если настроено) iss/aud токена.

    ``exp`` обязателен только при ``JWT_REQUIRE_EXP=true``; по умолчанию
    бессрочные токены (без ``exp``) принимаются. Если ``exp`` присутствует —
    он валидируется как обычно (просроченный токен отклоняется).

    Если в токене есть claims ``iss``/``aud``, но сервер их не настраивал
    (JWT_ISSUER/JWT_AUDIENCE пустые) — проверяем, что значение совпадает с
    ``app_name``: это допускает токены, выпущенные этим сервисом/скриптом,
    и при этом не даёт принять чужой токен с другим iss/aud.
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
    scopes = frozenset(known[item] for item in raw if item in known)
    # Упрощение: токен без scope/role = универсальный (все права).
    return scopes if scopes else frozenset(ALL_SCOPES)


# security_scheme: HTTPBearer нужен, чтобы в Swagger UI (/docs) появилась
# кнопка "Authorize" и поле для Bearer-токена; auto_error=False — сообщения
# об ошибках формируем сами (единые для всего сервиса).
bearer_scheme = HTTPBearer(auto_error=False, description="JWT из get_token.py")


async def get_principal(
    settings: Annotated[Settings, Depends(get_settings)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ] = None,
) -> Principal:
    """Единственный канал доступа: JWT в заголовке Authorization."""
    authorization = credentials.credentials if credentials else None
    if not credentials or not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Требуется заголовок 'Authorization: Bearer <token>'. "
                "В Swagger UI (/docs): нажмите кнопку 'Authorize' (вверху справа, "
                "замок 🔒) и вставьте токен из get_token.py. Если кнопки нет — "
                "обновите страницу с очисткой кэша (Ctrl+F5)."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = (credentials.scheme or "").strip()
    if token.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ожидается заголовок 'Authorization: Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(authorization.strip(), settings)
    return Principal(
        subject=str(payload.get("sub")),
        scopes=_extract_scopes(payload),
        issuer=payload.get("iss"),
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
    ttl_seconds: int | None = None,
) -> str:
    """Выпускает JWT. ``ttl_seconds=None`` (или ``0``) — токен БЕЗ ``exp``, т.е. бессрочный."""
    now = datetime.now(timezone.utc)
    payload: dict = {
        "sub": subject,
        "scope": " ".join(scopes),
        "iat": now,
    }
    if settings.jwt_issuer:
        payload["iss"] = settings.jwt_issuer
    if settings.jwt_audience:
        payload["aud"] = settings.jwt_audience
    if ttl_seconds:
        payload["exp"] = now.timestamp() + ttl_seconds
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
