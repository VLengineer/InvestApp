"""Сервис company_profiles: загрузка cp.json, склейка текста, эмбеддинги, запись в БД.

Логика повторяет подход RAG-модуля (слои routes -> services -> repositories):
  1) читаем источник (cp.json),
  2) формируем «склеенный» текст профиля по приоритету полей,
  3) получаем вектор через Ollama (async-клиент app/clients/ollama.py),
  4) upsert-им строки в таблицу company_profiles (pgvector) через репозиторий.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.clients.ollama import OllamaEmbeddingClient
from app.repositories.company_profile_repository import CompanyProfileRepository

logger = logging.getLogger(__name__)

NEWS_TRIGGER_CATEGORIES = ("positive", "negative", "neutral")


def _as_text(value: Any) -> str | None:
    """Значение для колонок типа TEXT: списки склеиваем в читаемую строку.

    В схеме init_db/03_init_company_profiles.sql колонка competitors — TEXT,
    а в cp.json это список, поэтому JSON-дамп туда класть нельзя.
    """
    if value is None:
        return None
    if isinstance(value, list):
        joined = _join_list(value)
        return joined or None
    return str(value)


# --------------------------------------------------------------------------- #
# 1. Чтение JSON
# --------------------------------------------------------------------------- #
def _candidate_paths(settings: Settings, path: str | Path | None) -> list[Path]:
    """Список путей-кандидатов для cp.json (первый существующий используется).

    Порядок: явный path/env -> надёжный путь из Settings -> дефолт образа
    (/app/company_profiles/cp.json) -> DEFAULT_CP_JSON. Относительные пути
    считаются от корня сервиса, а не от CWD процесса.
    """
    candidates: list[Path] = []

    def add(p: Path | None) -> None:
        if p is None:
            return
        p = Path(p)
        if not p.is_absolute():
            p = Path(__file__).resolve().parents[2] / p
        if p not in candidates:
            candidates.append(p)

    add(Path(path)) if path else None
    add(settings.company_profiles_json_path)
    add(Path("/app/company_profiles/cp.json"))
    add(DEFAULT_CP_JSON)
    return candidates


def resolve_cp_json(settings: Settings, path: str | Path | None = None) -> Path:
    """Вернуть первый реально существующий кандидат; иначе — основной (для 404)."""
    for p in _candidate_paths(settings, path):
        if p.is_file():
            return p
    return _candidate_paths(settings, path)[0]


def load_company_profiles(settings: Settings, path: str | Path | None = None) -> list[dict[str, Any]]:
    """Прочитать профили из cp.json.

    Путь фиксированный: ``company_profiles/cp.json`` рядом с кодом микросервиса
    (в контейнере копируется в образ Dockerfile'ом); переопределяется только
    через env ``COMPANY_PROFILES_JSON`` — из запроса путь указывать не нужно.

    Разрешение пути инкапсулировано в ``Settings.company_profiles_json_path``
    (см. ``_resolve_company_profiles_json`` в app/core/config.py): относительные
    пути считаются от корня сервиса, а не от CWD процесса, поэтому файл
    находится одинаково и в Docker (``/app/company_profiles/cp.json``),
    и при локальном запуске из любой папки. Дополнительно сервис пробует
    несколько канонических путей (см. ``_candidate_paths``), чтобы «cp.json not
    found» не возникал из-за устаревшего/хостового значения env или запуска
    непересобранным образом.
    """
    candidates = _candidate_paths(settings, path)
    resolved = next((p for p in candidates if p.is_file()), candidates[0])
    try:
        with open(resolved, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as exc:
        tried = "; ".join(str(p) for p in candidates)
        raise FileNotFoundError(
            f"{resolved}. Испробованные пути: {tried}. Проверьте, что файл "
            "копируется в образ (Dockerfile: COPY company_profiles ./company_profiles) "
            "и что образ пересобран после его добавления/изменения: "
            "docker compose build --no-cache python_test && docker compose up -d python_test"
        ) from exc
    if isinstance(data, dict):  # допускаем {"profiles": [...]}
        data = data.get("profiles") or data.get("companies") or list(data.values())
    if not isinstance(data, list):
        raise ValueError(f"Unexpected structure in {resolved}: expected list of profiles")
    return data


# --------------------------------------------------------------------------- #
# 2. Склейка текста для эмбеддинга (по приоритету полей)
# --------------------------------------------------------------------------- #
def _join_list(items: Any, sep: str = ", ") -> str:
    if items is None:
        return ""
    if isinstance(items, str):
        return items
    if isinstance(items, list):
        parts: list[str] = []
        for it in items:
            if isinstance(it, dict):
                # related_entities / key_figures: name + type/position.
                # скобки балансируем явно: strip("() ") срезал и закрывающую ")"
                # из "(Газпромбанк (competitor)" — получалось "Газпромбанк (competitor"
                name = str(it.get("name") or it.get("title") or "").strip()
                extra = str(
                    it.get("position") or it.get("type") or it.get("role") or ""
                ).strip()
                if name and extra:
                    parts.append(f"{name} ({extra})")
                elif name or extra:
                    parts.append(name or extra)
            else:
                parts.append(str(it))
        return sep.join(p for p in parts if p)
    return str(items)


def build_embed_text(profile: dict[str, Any]) -> str:
    """Склеить поля профиля в один текст согласно заданному приоритету."""
    nt = profile.get("news_triggers") or {}
    news_all: list[str] = []
    if isinstance(nt, dict):
        for cat in NEWS_TRIGGER_CATEGORIES:
            news_all.extend(str(x) for x in (nt.get(cat) or []))
    elif isinstance(nt, list):
        news_all = [str(x) for x in nt]

    identity = " ".join(
        str(profile[k]).strip()
        for k in ("company_name", "ticker", "figi")
        if profile.get(k)
    )

    ordered_fields: list[tuple[str, str]] = [
        ("Компания", identity),                                             # company_name + ticker + figi
        ("Описание", (profile.get("description") or "").strip()),           # description
        ("Бизнес-модель", (profile.get("business_model") or "").strip()),   # business_model
        ("Ключевые слова", _join_list(profile.get("keywords_for_embedding"))),
        ("Связанные сущности", _join_list(profile.get("related_entities"))),
        ("Новостные триггеры", _join_list(news_all)),                        # все три категории
        ("Ключевые продукты", _join_list(profile.get("key_products"))),
        ("Ключевые фигуры", _join_list(profile.get("key_figures"))),         # имена + должности
        ("Рыночная позиция", (profile.get("market_position") or "").strip()),
        ("Исторические паттерны", (profile.get("historical_patterns") or "").strip()),
        ("Целевая аудитория", (profile.get("target_audience") or "").strip()),
        ("География", (profile.get("geography") or "").strip()),
        ("Конкуренты", _join_list(profile.get("competitors"))),
        ("Регуляторные зависимости", (profile.get("regulatory_dependencies") or "").strip()),
        ("Технологический стек", _join_list(profile.get("technology_stack"))),
        ("Финансовые метрики", _join_list(profile.get("financial_metrics_of_interest"))),
        ("Факторы корреляции", _join_list(profile.get("correlation_factors"))),
    ]

    lines = [f"{label}: {value}" for label, value in ordered_fields if value]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 3. Вектор -> строка для pgvector
# --------------------------------------------------------------------------- #
def vector_to_pg(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


# --------------------------------------------------------------------------- #
# 4. Сервис (используется из app/api/routes/company_profiles.py)
# --------------------------------------------------------------------------- #
class CompanyProfilesService:
    """Ингест cp.json и семантический поиск по профилям компаний."""

    def __init__(
        self,
        settings: Settings,
        embedder: OllamaEmbeddingClient,
        repository: CompanyProfileRepository,
    ) -> None:
        self._settings = settings
        self._embedder = embedder
        self._repository = repository

    async def ingest(self, json_path: str | None = None) -> dict[str, Any]:
        """Основной процесс: cp.json -> эмбеддинги -> таблица company_profiles."""
        profiles = load_company_profiles(self._settings, json_path)
        return await self.ingest_from_profiles(profiles)

    async def ingest_from_profiles(self, profiles: list[dict[str, Any]]) -> dict[str, Any]:
        """Склейка -> эмбеддинг -> upsert для уже прочитанного списка профилей.

        Вынесено отдельно, чтобы список профилей можно было передать напрямую
        (и протестировать без файла/БД), а ingest() остался тонкой обёрткой.
        """
        await self._repository.ensure_schema()

        inserted = updated = failed = 0
        for prof in profiles:
            figi = (prof.get("figi") or "").strip() or None
            text = build_embed_text(prof)
            try:
                embedding = await self._embedder.embed(text)
            except Exception as exc:  # noqa: BLE001
                logger.error("Embedding failed for %s: %s", figi or prof.get("company_name"), exc)
                failed += 1
                continue

            existed = await self._repository.exists(figi)
            values = (
                prof.get("company_name"),
                prof.get("ticker"),
                figi,
                prof.get("description"),
                prof.get("business_model"),
                prof.get("market_position"),
                prof.get("target_audience"),
                prof.get("geography"),
                _as_text(prof.get("competitors")),
                prof.get("regulatory_dependencies"),
                json.dumps(prof.get("technology_stack"), ensure_ascii=False),
                prof.get("historical_patterns"),
                json.dumps(prof.get("keywords_for_embedding"), ensure_ascii=False),
                json.dumps(prof.get("related_entities"), ensure_ascii=False),
                json.dumps(prof.get("news_triggers"), ensure_ascii=False),
                json.dumps(prof.get("key_products"), ensure_ascii=False),
                json.dumps(prof.get("key_figures"), ensure_ascii=False),
                json.dumps(prof.get("financial_metrics_of_interest"), ensure_ascii=False),
                json.dumps(prof.get("correlation_factors"), ensure_ascii=False),
                vector_to_pg(embedding),
                self._settings.embedding_model,
                len(embedding),
                text,
            )
            await self._repository.upsert_profile(values)
            if existed:
                updated += 1
            else:
                inserted += 1
            logger.info("Upserted profile: %s (%s)", prof.get("company_name"), figi)

        return {
            "total": len(profiles),
            "inserted": inserted,
            "updated": updated,
            "failed": failed,
        }

    async def list_profiles(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return await self._repository.list_profiles(limit=limit, offset=offset)

    async def get_profile(self, figi: str) -> dict[str, Any] | None:
        return await self._repository.get_by_figi(figi)

    async def search_similar(
        self,
        query: str,
        limit: int = 5,
        min_rel_similarity: float | None = None,
    ) -> list[dict[str, Any]]:
        """Косинусный поиск по эмбеддингу профиля (для эндпоинта /company-profiles/search).

        Порог задаётся по ОТНОСИТЕЛЬНОМУ сходству (см. репозиторий): нерелевантный
        запрос («null», набор клавиш и т.п.) вернёт пустой список, а не первую
        попавшуюся компанию с косинусом 0.65. ``min_rel_similarity=None`` — взять
        значение из настроек (env ``CP_SEARCH_MIN_REL_SIMILARITY``).
        """
        query = (query or "").strip()
        if not query:
            return []

        embedding = await self._embedder.embed(f"search: {query}")

        return await self._repository.search_by_vector(
            vector_to_pg(embedding),
            limit,
            min_similarity=min_rel_similarity or None,
            recall_depth=self._settings.cp_search_recall_depth,
        )


# Путь к cp.json по умолчанию (папка микросервиса python_test/company_profiles/).
# DDL таблицы при этом берётся из init_db/03_init_company_profiles.sql — единый
# источник схемы для docker-entrypoint-initdb.d и для ensure_schema() (см. app/db).
DEFAULT_CP_JSON = (
    Path(__file__).resolve().parents[2] / "company_profiles" / "cp.json"
)
