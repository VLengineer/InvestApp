"""DDL таблицы ``company_profiles`` (идемпотентная, зеркалит init_db/03_init_company_profiles.sql).

Как и app/db/database.py для RAG-таблиц: схемы создаёт docker-entrypoint-initdb.d,
но тот же DDL нужен для локального запуска/тестов против обычной PostgreSQL.
"""

from __future__ import annotations

import os

COMPANY_PROFILES_DDL_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),  # корень python_test/
        "company_profiles",
        "03_init_company_profiles.sql",
    )
)


async def ensure_company_profiles_table(conn) -> None:  # noqa: ANN001 - asyncpg.Connection | Pool-acquired conn
    """Создать таблицу company_profiles, если её ещё нет (IF NOT EXISTS)."""
    with open(COMPANY_PROFILES_DDL_PATH, encoding="utf-8") as f:
        sql = f.read()
    for stmt in filter(None, (s.strip() for s in sql.split(";"))):
        if not stmt.startswith("--"):
            await conn.execute(stmt)
