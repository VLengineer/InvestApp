"""Диагностика авторизации: почему сервер отвергает конкретный токен.

Обычный 401 («Недействительный или просроченный токен доступа») намеренно НЕ
раскрывает причину — это защита от перечисления/подбора. Но при настройке
Swagger/n8n такая «глухая» ошибка мешает: непонятно, секрет не совпал,
не хватает ``iss``/``aud`` или токен просрочен.

Отсюда две функции:

* :func:`explain_token_failure` — точный разбор причин (для внутреннего
  использования и эндпоинта ``POST /auth/verify-token``, который доступен
  только держателю admin-ключа);
* :func:`log_token_rejection` — безопасная запись причины в лог (только имена
  claims и их значения из *настроек сервера*, никогда — подпись токена,
  секреты и API-ключи).
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from datetime import datetime, timezone
from typing import Any

import jwt
from jwt import PyJWTError

from app.core.config import Settings

logger = logging.getLogger(__name__)

ALGORITHM_WHITELIST = ["HS256"]


def _b64url_json(segment: str) -> dict[str, Any]:
    """Декодирует JWT-сегмент (base64url без ``=``) в dict; без проверки подписи."""
    pad = "=" * (-len(segment) % 4)
    raw = base64.urlsafe_b64decode(segment.replace("-", "+").replace("_", "/") + pad)
    return json.loads(raw.decode("utf-8"))


def peek_token(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Возвращает (header, payload) локально подписанного токена для диагностики.

    Подпись НЕ проверяется — функция нужна только чтобы показать оператору,
    какие claims реально ушли в запросе. Для чужого/битого токена бросает
    ``ValueError``.
    """
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise ValueError("Токен должен содержать три части 'xxxx.yyyy.zzzz' (JWT)")
    try:
        return _b64url_json(parts[0]), _b64url_json(parts[1])
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError(f"Не удалось разобрать JWT: {exc}") from exc


def explain_token_failure(token: str, settings: Settings) -> list[str]:
    """Список человекочитаемых причин, почему сервер отвергнет этот токен.

    Пустой список == токен валиден. Проверки полностью повторяют
    :func:`app.core.security.decode_token`.
    """
    problems: list[str] = []
    try:
        header, payload = peek_token(token)
    except ValueError as exc:
        return [str(exc)]

    alg = str(header.get("alg", ""))
    if alg not in ALGORITHM_WHITELIST:
        problems.append(f"алгоритм «{alg or '—'}» не разрешён; ожидается один из {ALGORITHM_WHITELIST}")

    for claim in ("sub", "iat"):
        if claim not in payload:
            problems.append(f"в токене нет обязательного claim «{claim}»")

    now = datetime.now(timezone.utc).timestamp()
    leeway = settings.jwt_leeway_s
    exp = payload.get("exp")
    if exp is None and settings.jwt_require_exp:
        problems.append("в токене нет «exp», а JWT_REQUIRE_EXP=true")
    if isinstance(exp, (int, float)) and exp + leeway < now:
        problems.append(f"токен просрочен: exp истёк {datetime.fromtimestamp(exp, timezone.utc):%Y-%m-%d %H:%M:%S} UTC")
    iat = payload.get("iat")
    if isinstance(iat, (int, float)) and iat - leeway > now:
        problems.append(
            f"iat в будущем ({datetime.fromtimestamp(iat, timezone.utc):%Y-%m-%d %H:%M:%S} UTC) — проверьте часы"
        )

    # 1) подпись: если она не проходит, остальные придирки лишь шумят — но их всё
    #    равно стоит показать (частая ситуация: секрет совпал, а iss/aud забыли).
    signature_error: PyJWTError | None = None
    try:
        jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=ALGORITHM_WHITELIST,
            options={"verify_signature": True, "verify_exp": False, "verify_iss": False, "verify_aud": False},
        )
    except PyJWTError as exc:
        signature_error = exc

    if isinstance(signature_error, jwt.InvalidSignatureError):
        problems.insert(
            0,
            "подпись не совпадает: токен выпущен с другим JWT_SECRET_KEY "
            "(или секрет в контейнере отличается от того, что у вас в .env)",
        )
    elif signature_error is not None:
        problems.insert(0, f"{type(signature_error).__name__}: {signature_error}")

    # 2) iss / aud: сервер требует их, если заданы в env (JWT_ISSUER / JWT_AUDIENCE)
    for claim, env_name, configured in (
        ("iss", "JWT_ISSUER", settings.jwt_issuer),
        ("aud", "JWT_AUDIENCE", settings.jwt_audience),
    ):
        if not configured:
            continue
        if claim not in payload:
            problems.append(
                f"в токене нет claim «{claim}», а сервер ожидает «{configured}» (env {env_name}); "
                f"добавьте его при выпуске токена (get_token.py --{claim} \"{configured}\")"
            )
        elif str(payload[claim]) != str(configured):
            problems.append(f"claim «{claim}» = «{payload[claim]}», сервер ожидает «{configured}» (env {env_name})")

    return problems


def log_token_rejection(exc: Exception, token: str, settings: Settings) -> None:
    """Логирует причину отказа с диагностикой, не раскрывая секретов наружу."""
    try:
        _, payload = peek_token(token)
        hints = "; ".join(explain_token_failure(token, settings))
        subject = payload.get("sub")
    except ValueError:
        hints, subject = "разбор токена не удался", None
    logger.warning(
        "Отклонён токен доступа (sub=%s, iss=%s, aud=%s, exp=%s): %s | %s",
        subject,
        payload.get("iss") if subject is not None else None,
        payload.get("aud") if subject is not None else None,
        payload.get("exp") if subject is not None else None,
        type(exc).__name__,
        hints,
    )
