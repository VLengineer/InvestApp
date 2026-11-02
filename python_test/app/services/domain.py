"""Доменная модель (domain layer): не знает ни про HTTP, ни про БД, ни про Ollama."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def canonical_json(obj: Any) -> str:
    """Каноническое JSON-представление: стабильный порядок ключей, unicode as-is."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(obj: Any) -> str:
    """SHA-256 от канонического JSON — механизм защиты от дублей (см. init_db SQL)."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


CONCEPT_TEXT_FIELDS: tuple[str, ...] = (
    "title",
    "category",
    "essence",
    "formula",
    "interpretation",
    "sector_specifics",
    "limitations",
    "related_concepts",
    "search_keywords",
    "source_text_excerpt",
)


@dataclass(frozen=True, slots=True)
class Concept:
    """Один концепт = один документ в ``kb_documents`` и одна строка эмбеддинга."""

    source_path: str
    concept_id: str
    title: str | None
    category: str | None
    payload: dict[str, Any]
    text: str
    hash: str

    @property
    def short_hash(self) -> str:
        return self.hash[:12]


@dataclass(slots=True)
class SourceFile:
    path: Path
    rel_path: str
    concepts: list[Concept] = field(default_factory=list)
    error: str | None = None


def render_embed_text(payload: dict[str, Any], max_chars: int) -> str:
    """Собирает текст для эмбеддинга из значимых полей концепта.

    Модель nomic-embed-text ожидает инструкцию вида ``search: <query>`` /
    ``doc: <document>``; здесь используется префикс ``doc:``.
    """
    parts: list[str] = []
    for key in CONCEPT_TEXT_FIELDS:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            value = "; ".join(str(v) for v in value)
        elif isinstance(value, dict):
            value = canonical_json(value)
        text = str(value).strip()
        if text:
            parts.append(f"{key}: {text}")
    body = "\n".join(parts)
    if len(body) > max_chars:
        body = body[:max_chars].rstrip() + " …"
    return f"doc: {body}"


def extract_concepts(raw: Any, *, rel_path: str, max_chunk_chars: int) -> list[Concept]:
    """Рекурсивно находит все словари-концепты (с обязательными id+title).

    Файлы «Общий json» имеют вид ``[[{...}, {...}], [{...}], ...]`` — поэтому
    нужен обход любой вложенности, а не только верхний уровень.
    """
    found: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "id" in node and "title" in node:
                found.append(node)
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(raw)

    concepts: list[Concept] = []
    for item in found:
        digest = content_hash(item)
        if digest in seen_hashes:  # дубликаты внутри одного файла
            continue
        seen_hashes.add(digest)
        concepts.append(
            Concept(
                source_path=rel_path,
                concept_id=str(item["id"]),
                title=str(item["title"])[:512],
                category=(str(item["category"])[:256] if item.get("category") else None),
                payload=item,
                text=render_embed_text(item, max_chunk_chars),
                hash=digest,
            )
        )
    return concepts
