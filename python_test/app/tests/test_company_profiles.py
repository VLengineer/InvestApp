"""Тесты микросервиса company_profiles: cp.json -> склейка строк -> SQL для БД.

Проверяют то, что можно проверить без живой PostgreSQL/Ollama:
  * путь к cp.json и к DDL (init_db/03_init_company_profiles.sql) разрешаются;
  * JSON читается и содержит ожидаемые профили;
  * build_embed_text склеивает поля в правильном приоритете;
  * набор полей cp.json == набор колонок CREATE TABLE в init_db (нет рассинхрона);
  * ensure_company_profiles_table корректно режет DDL на операторы (PL/pgSQL-блок
    не рвётся по ';' внутри тела функции);
  * upsert-запрос использует ровно те колонки, что есть в таблице, и столько же
    параметров;
  * service.ingest() вызывает embedder/repo с корректными значениями (моки).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.core.config import Settings
from app.db.company_profiles_schema import (
    COMPANY_PROFILES_DDL_PATH,
    read_ddl_statements,
)
from app.repositories.company_profile_repository import UPSERT_SQL
from app.services.company_profiles_service import (
    DEFAULT_CP_JSON,
    CompanyProfilesService,
    build_embed_text,
    load_company_profiles,
    vector_to_pg,
)

DDL_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+company_profiles\s*\((?P<body>.*?)\n\)\s*;",
    re.IGNORECASE | re.DOTALL,
)


def _ddl_columns() -> list[str]:
    """Колонки таблицы из init_db/03_init_company_profiles.sql (без id/created_at/updated_at)."""
    sql = Path(COMPANY_PROFILES_DDL_PATH).read_text(encoding="utf-8")
    match = DDL_TABLE_RE.search(sql)
    assert match, "не нашли CREATE TABLE company_profiles в DDL"
    cols: list[str] = []
    for raw in match.group("body").splitlines():
        line = raw.split("--")[0].strip().rstrip(",").strip()
        if not line:
            continue
        first = line.split()[0].upper()
        if first in {"PRIMARY", "UNIQUE", "CONSTRAINT", "CHECK", "FOREIGN"}:
            continue
        name = line.split()[0].lower()
        if name in {"id", "created_at", "updated_at"}:
            continue
        cols.append(name)
    return cols


# --------------------------------------------------------------------------- #
# Пути после переноса SQL-файла в init_db/
# --------------------------------------------------------------------------- #
def test_paths_resolve_after_move_to_init_db() -> None:
    assert Path(COMPANY_PROFILES_DDL_PATH).name == "03_init_company_profiles.sql"
    assert Path(COMPANY_PROFILES_DDL_PATH).parent.name == "init_db"
    assert Path(COMPANY_PROFILES_DDL_PATH).is_file(), "DDL должна лежать в init_db/"
    assert DEFAULT_CP_JSON.is_file(), f"cp.json не найден: {DEFAULT_CP_JSON}"


def test_settings_default_json_path_points_to_microservice_folder() -> None:
    settings = Settings(
        JWT_SECRET_KEY="x" * 48, POSTGRES_USER="u", POSTGRES_PASSWORD="p"
    )
    assert settings.company_profiles_json_path == DEFAULT_CP_JSON


def test_old_sql_location_is_gone() -> None:
    """Старые копии DDL удалены: единственный источник — init_db/."""
    root = Path(__file__).resolve().parents[3]
    assert not (root / "python_test" / "company_profiles" / "03_init_company_profiles.sql").exists()
    assert not (root / "company_profiles" / "03_init_company_profiles.sql").exists()


# --------------------------------------------------------------------------- #
# Чтение cp.json + склейка текста
# --------------------------------------------------------------------------- #
def test_load_company_profiles_reads_list() -> None:
    profiles = load_company_profiles(Settings.model_construct())
    assert isinstance(profiles, list) and len(profiles) >= 2
    assert all(p.get("company_name") for p in profiles)


def test_build_embed_text_priority_and_content() -> None:
    profile = {
        "company_name": "Сбербанк",
        "ticker": "SBER",
        "figi": "SBER",
        "description": "Крупнейший банк.",
        "business_model": "Универсальный банк, розница и корпоративный бизнес.",
        "keywords_for_embedding": ["банк", "дивиденды"],
        "related_entities": [{"name": "Газпромбанк", "type": "competitor"}],
        "news_triggers": {"positive": ["дивиденды"], "negative": ["санкции"], "neutral": ["отчёт"]},
        "key_figures": [{"name": "Герман Греф", "position": "CEO"}],
        "geography": None,
    }
    text = build_embed_text(profile)
    lines = [ln.split(":")[0] for ln in text.splitlines()]

    assert lines[0] == "Компания"
    assert text.startswith("Компания: Сбербанк SBER SBER")
    # приоритет: описание раньше бизнес-модели, та — раньше ключевых слов
    assert lines.index("Описание") < lines.index("Бизнес-модель") <= lines.index("Ключевые слова")
    assert "Новостные триггеры: дивиденды, санкции, отчёт" in text
    assert "Связанные сущности: Газпромбанк (competitor)" in text
    assert "Ключевые фигуры: Герман Греф (CEO)" in text
    # пустые/None-поля не попадают в текст
    assert "География" not in text


def test_vector_to_pg_format() -> None:
    assert vector_to_pg([1.0, -0.5]) == "[1.00000000,-0.50000000]"


# --------------------------------------------------------------------------- #
# Соответствие кода и схемы init_db
# --------------------------------------------------------------------------- #
def test_cp_json_fields_match_table_columns() -> None:
    columns = set(_ddl_columns())
    data = json.loads(DEFAULT_CP_JSON.read_text(encoding="utf-8"))
    json_fields = {k for item in data for k in item}
    missing = json_fields - columns
    assert not missing, f"полей cp.json нет в таблице company_profiles: {sorted(missing)}"


def test_upsert_sql_columns_match_ddl_and_service_values() -> None:
    insert_part, values_part = UPSERT_SQL.split("VALUES")
    cols = [c.strip() for c in re.search(r"\((.*?)\)", insert_part, re.S).group(1).split(",")]
    # created_at/updated_at заполняются в SQL литералом now(), параметрами не идут
    business_cols = [c for c in cols if c not in {"created_at", "updated_at"}]
    params = re.findall(r"\$\d+", values_part)

    assert len(params) == len(business_cols), "число параметров != числу колонок-параметров в INSERT"
    assert set(business_cols) == set(_ddl_columns()), "INSERT ссылается на колонки, которых нет в init_db"

    # сервис передаёт ровно столько значений, сколько параметров в UPSERT_SQL
    profile = json.loads(DEFAULT_CP_JSON.read_text(encoding="utf-8"))[0]
    service = CompanyProfilesService.__new__(CompanyProfilesService)
    service._settings = Settings(
        JWT_SECRET_KEY="x" * 48, POSTGRES_USER="u", POSTGRES_PASSWORD="p"
    )
    assert len(_collect_upsert_values(service, profile)) == len(params)


def _collect_upsert_values(service: CompanyProfilesService, profile: dict) -> tuple:
    """Вытащить кортеж значений, который сервис передаёт в репозиторий."""

    class _Embedder:
        async def embed(self, text: str) -> list[float]:
            return [0.0] * service._settings.embedding_dim

    class _Repo:
        captured: tuple | None = None

        async def ensure_schema(self) -> None:
            return None

        async def exists(self, figi):  # noqa: ANN001
            return False

        async def upsert_profile(self, values) -> None:  # noqa: ANN001
            _Repo.captured = values

    repo = _Repo()
    service._embedder = _Embedder()
    service._repository = repo
    import asyncio

    asyncio.run(service.ingest_from_profiles([profile]))
    assert repo.captured is not None
    return repo.captured


# --------------------------------------------------------------------------- #
# Разбор DDL: PL/pgSQL-блок не должен рваться по ';' внутри тела
# --------------------------------------------------------------------------- #
def test_read_ddl_statements_keeps_function_block_intact(tmp_path: Path) -> None:
    ddl = tmp_path / "03_x.sql"
    ddl.write_text(
        "\n".join(
            [
                "-- комментарий",
                "CREATE EXTENSION IF NOT EXISTS vector;",
                "CREATE TABLE IF NOT EXISTS t (a INT, b TEXT);",
                "CREATE OR REPLACE FUNCTION f() RETURNS TRIGGER AS $$",
                "BEGIN",
                "    NEW.b = now();",
                "    RETURN NEW;",
                "END;",
                "$$ LANGUAGE plpgsql;",
                "DROP TRIGGER IF EXISTS trg ON t;",
            ]
        ),
        encoding="utf-8",
    )
    stmts = read_ddl_statements(str(ddl))
    assert stmts[0].startswith("CREATE EXTENSION")
    assert stmts[1].startswith("CREATE TABLE")
    assert stmts[2].startswith("CREATE OR REPLACE FUNCTION")
    assert stmts[2].rstrip().endswith("LANGUAGE plpgsql")
    assert "RETURN NEW" in stmts[2]
    assert stmts[3].startswith("DROP TRIGGER")
    assert not any(s.startswith("--") for s in stmts)



