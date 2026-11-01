"""Генератор БЕССРОЧных JWT-токенов (HS256) для RAG-индексатора.

Токен не содержит claim ``exp`` — срок действия отсутствует, сервер его тоже
не требует (JWT_REQUIRE_EXP=false в python_test/.env).

Использование:
    python get_token.py --secret "<JWT_SECRET_KEY>" --sub external-service
    python get_token.py --secret "<JWT_SECRET_KEY>" --sub n8n --scope rag:read --scope rag:index
    python get_token.py --secret "<JWT_SECRET_KEY>" --sub n8n --ttl 3600   # если нужен токен на час

Секрет взять из python_test/.env (JWT_SECRET_KEY) или сгенерировать: python secret.py
"""

import argparse
import json
import time

import jwt


def build_token(secret: str, subject: str, scopes: list[str], iss: str | None, aud: str | None, ttl: int | None) -> str:
    payload = {
        "sub": subject,
        "iat": int(time.time()),  # обязателен: сервер проверяет require=["iat", "sub"]
        # "exp" НЕ добавляем -> токен бессрочный
    }
    if iss:
        payload["iss"] = iss
    if aud:
        payload["aud"] = aud
    if scopes:
        payload["scope"] = " ".join(scopes)
    if ttl:
        payload["exp"] = int(time.time()) + ttl
    return jwt.encode(payload, secret, algorithm="HS256")


def main() -> None:
    parser = argparse.ArgumentParser(description="Выпустить бессрочный JWT (HS256)")
    parser.add_argument("--secret", help="JWT_SECRET_KEY (если не задан — запросится интерактивно)")
    parser.add_argument("--sub", default="external-service", help="claim sub (имя пользователя/сервиса)")
    parser.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        metavar="SCOPE",
        help="rag:read / rag:index / rag:admin (можно несколько раз)",
    )
    # По умолчанию iss/aud НЕ добавляются: сервер проверяет их только если заданы
    # JWT_ISSUER / JWT_AUDIENCE. Если у сервера они заданы — передайте --iss/--aud.
    parser.add_argument("--iss", default=None, help="claim iss (совпадает с JWT_ISSUER сервера; по умолчанию без iss)")
    parser.add_argument("--aud", default=None, help="claim aud (совпадает с JWT_AUDIENCE сервера; по умолчанию без aud)")
    parser.add_argument("--ttl", type=int, default=0, help="секунды до истечения; 0 — бессрочный (по умолчанию)")
    args = parser.parse_args()

    secret = args.secret or input("Вставьте секрет (JWT_SECRET_KEY): ").strip()
    token = build_token(
        secret=secret,
        subject=args.sub,
        scopes=args.scopes or [],
        iss=args.iss,
        aud=args.aud or None,
        ttl=args.ttl or None,
    )

    print(token)
    claims = jwt.decode(token, options={"verify_signature": False})
    print(json.dumps(claims, ensure_ascii=False, indent=2), flush=True)
    print("exp отсутствует -> токен бессрочный" if "exp" not in claims else f"истекает: {claims['exp']}")


if __name__ == "__main__":
    main()
