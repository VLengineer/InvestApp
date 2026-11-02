"""DDL таблицы ``company_profiles`` — читается из ``init_db/03_init_company_profiles.sql``.

Единый источник схемы: файл лежит в ``init_db/`` и монтируется в
docker-entrypoint-initdb.d (см. docker-compose.yml), а репозиторий при старте
выполняет ровно его же — чтобы локальный запуск/тесты против обычной PostgreSQL
создавали такую же таблицу, что и в контейнере, без рассинхрона DDL.
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

# .../python_test/app/db/<файл> -> parents[2]=python_test, parents[1]=корень репозитория
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../python_test/app
_INIT_DB_DIR = os.path.normpath(os.path.join(_APP_DIR, os.pardir, os.pardir, "init_db"))

COMPANY_PROFILES_DDL_PATH = os.environ.get(
    "COMPANY_PROFILES_DDL",
    os.path.join(_INIT_DB_DIR, "03_init_company_profiles.sql"),
)


def _strip_comments(chunk: str) -> str:
    """Убрать комментарии построчно ('...' и $$-строки в этом DDL не встречаются)."""
    return "\n".join(line.split("--")[0] for line in chunk.splitlines())


def read_ddl_statements(path: str = COMPANY_PROFILES_DDL_PATH) -> list[str]:
    """Прочитать SQL-файл и вернуть список исполняемых операторов.

    Файл инициализации содержит комментарии и блоки PL/pgSQL с телами, внутри
    которых есть ``;`` (например ``BEGIN ... END;`` в триггерной функции),
    поэтому наивный split по ``;`` ломает такие блоки. Здесь сначала вырезаются
    комментарии, затем блоки ``CREATE FUNCTION ... $$ ... $$ LANGUAGE ...;`` —
    целиком, и только оставшийся текст разбивается по ``;``.
    """
    with open(path, encoding="utf-8") as f:
        sql = _strip_comments(f.read())

    statements: list[str] = []
    pos = 0
    block_re = re.compile(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\b.*?\$\$.*?\$\$\s*(?:LANGUAGE\s+\w+)?\s*;",
        re.IGNORECASE | re.DOTALL,
    )
    while pos < len(sql):
        match = block_re.search(sql, pos)
        chunk = sql[pos : match.start()] if match else sql[pos:]
        statements.extend(s.strip() for s in chunk.split(";") if s.strip())
        if not match:
            break
        statements.append(match.group().strip())
        pos = match.end()

    return [s for s in statements if not s.startswith("--")]


async def ensure_company_profiles_table(conn) -> None:  # noqa: ANN001 - asyncpg.Connection | Pool-acquired conn
    """Создать таблицу company_profiles, если её ещё нет (DDL идемпотентна).

    Если файл схемы недоступен (например, в образе Docker он не копируется —
    схема там создаётся через docker-entrypoint-initdb.d), просто пропускаем:
    таблица уже создана инициализацией контейнера Postgres.
    """
    if not os.path.exists(COMPANY_PROFILES_DDL_PATH):
        logger.warning(
            "DDL %s не найден — ожидаем, что таблица company_profiles создана init_db",
            COMPANY_PROFILES_DDL_PATH,
        )
        return
    for stmt in read_ddl_statements():
        await conn.execute(stmt)
