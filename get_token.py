"""Генератор БЕССРОЧных JWT-токенов (HS256) для RAG-индексатора.

Токен не содержит claim ``exp`` — срок действия отсутствует, сервер его тоже
не требует (JWT_REQUIRE_EXP=false в python_test/.env).

ВАЖНО про iss/aud: если в python_test/.env заданы JWT_ISSUER и JWT_AUDIENCE,
сервер ОБЯЗАТЕЛЬНО ждёт эти claims в токене — без них будет 401
«Недействительный или просроченный токен доступа». Поэтому по умолчанию
скрипт сам читает python_test/.env и подставляет --iss/--aud из него.
Причины отказа можно посмотреть в логе контейнера (docker compose logs
python_test) или через POST /auth/verify-token с admin-ключом.

Использование:
    python get_token.py --sub n8n --scope rag:read --scope rag:index --aud rag-indexer --iss rag-indexer
    python get_token.py --secret "<JWT_SECRET_KEY>" --sub external-service --iss rag-indexer --aud rag-indexer
    python get_token.py --sub n8n --ttl 3600   # если нужен токен на час
    python get_token.py --no-env-file --iss "" --aud ""   # токены без iss/aud (если у сервера они не заданы)

Секрет взять из python_test/.env (JWT_SECRET_KEY) или сгенерировать: python secret.py
"""

import argparse
import json
import time
from pathlib import Path

import jwt


def _read_env_file(path: Path) -> dict[str, str]:
    """Мини-парсер .env (без зависимостей): KEY=VALUE, комментарии/# игнорируются."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #")[0].strip().strip("'\"")
        values[key.strip()] = value
    return values


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
    parser.add_argument("--env-file", default=str(Path(__file__).parent / "python_test" / ".env"),
                        help="файл .env сервиса (по умолчанию python_test/.env) — из него берутся секрет, iss и aud")
    parser.add_argument("--no-env-file", action="store_true", help="не читать .env, только явные флаги")
    parser.add_argument("--secret", help="JWT_SECRET_KEY (если не задан — берётся из .env, иначе спросит интерактивно)")
    parser.add_argument("--sub", default="external-service", help="claim sub (имя пользователя/сервиса)")
    parser.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        metavar="SCOPE",
        help="rag:read / rag:index / rag:admin (можно несколько раз)",
    )
    # По умолчанию iss/aud берутся из .env сервиса (JWT_ISSUER/JWT_AUDIENCE): если они
    # заданы у сервера, токен без этих claims получит 401. Пустая строка — не добавлять.
    parser.add_argument("--iss", default=None, help="claim iss (по умолчанию = JWT_ISSUER из .env; \"\" — не добавлять)")
    parser.add_argument("--aud", default=None, help="claim aud (по умолчанию = JWT_AUDIENCE из .env; \"\" — не добавлять)")
    parser.add_argument("--ttl", type=int, default=0, help="секунды до истечения; 0 — бессрочный (по умолчанию)")
    args = parser.parse_args()

    env = {} if args.no_env_file else _read_env_file(Path(args.env_file))
    secret = args.secret or env.get("JWT_SECRET_KEY") or input("Вставьте секрет (JWT_SECRET_KEY): ").strip()
    iss = args.iss if args.iss is not None else env.get("JWT_ISSUER")
    aud = args.aud if args.aud is not None else env.get("JWT_AUDIENCE")

    token = build_token(
        secret=secret,
        subject=args.sub,
        scopes=args.scopes or [],
        iss=iss or None,
        aud=aud or None,
        ttl=args.ttl or None,
    )

    print(token)
    claims = jwt.decode(token, options={"verify_signature": False})
    print(json.dumps(claims, ensure_ascii=False, indent=2), flush=True)
    print("exp отсутствует -> токен бессрочный" if "exp" not in claims else f"истекает: {claims['exp']}")
    missing = [c for c, want in (("iss", iss), ("aud", aud)) if not want and env.get(f"JWT_{c.upper()}")]
    if missing:
        print(
            f"ВНИМАНИЕ: в токене нет {', '.join(missing)}, а у сервера в .env они заданы "
            f"({env.get('JWT_ISSUER')}/{env.get('JWT_AUDIENCE')}) — Swagger вернёт 401."
        )


if __name__ == "__main__":
    main()
