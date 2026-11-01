"""Загрузчик JSON-документов из каталога knowledge_base.

Правила:
  * рекурсивно обходятся все файлы ``*.json`` во всех подпапках;
  * один JSON-файл содержит список концептов (допускается вложенность списков);
  * каждый концепт = один документ RAG-хранилища (чанки не нужны — документы уже структурированы);
  * файлы с синтаксическими ошибками не роняют индексацию: они попадают в отчёт ``errors``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("rag_indexer.loader")


@dataclass
class Concept:
    """Один документ базы знаний (один объект-концепт из JSON-файла)."""

    source_path: str          # относительный путь файла внутри knowledge_base
    concept_id: str           # поле "id" концепта (или "<file>#<n>", если id отсутствует)
    title: str | None
    category: str | None
    payload: dict[str, Any]   # полный исходный JSON концепта
    content_hash: str         # sha256 канонического JSON payload — защита от дублей
    text: str                 # текст для эмбеддинга

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "concept_id": self.concept_id,
            "title": self.title,
            "category": self.category,
            "content_hash": self.content_hash,
            "text_chars": len(self.text),
        }


@dataclass
class LoadReport:
    concepts: list[Concept] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    files_scanned: int = 0
    files_ok: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "files_scanned": self.files_scanned,
            "files_ok": self.files_ok,
            "concepts": len(self.concepts),
            "errors": self.errors,
        }


def build_embedding_text(concept: dict[str, Any]) -> str:
    """Собирает единый текст для эмбеддинга из структурированного концепта.

    Порядок полей фиксирован, чтобы эмбеддинг был детерминированным.
    """
    parts: list[str] = []
    for key in ("title", "category", "id"):
        val = concept.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(f"{key}: {val.strip()}")
    for key in ("essence", "formula", "interpretation", "sector_specifics",
                "limitations", "source_text_excerpt"):
        val = concept.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    keywords = concept.get("search_keywords")
    if isinstance(keywords, (list, tuple)):
        kw = ", ".join(str(k).strip() for k in keywords if str(k).strip())
        if kw:
            parts.append(f"search_keywords: {kw}")
    related = concept.get("related_concepts")
    if isinstance(related, (list, tuple)):
        rel = ", ".join(str(r).strip() for r in related if str(r).strip())
        if rel:
            parts.append(f"related_concepts: {rel}")
    # Неизвестные поля тоже включаем — иначе потеряем содержимое нестандартных документов.
    known = {"title", "category", "id", "essence", "formula", "interpretation",
             "sector_specifics", "limitations", "source_text_excerpt",
             "search_keywords", "related_concepts"}
    for key, val in concept.items():
        if key in known:
            continue
        rendered = _render(val)
        if rendered:
            parts.append(f"{key}: {rendered}")
    return "\n".join(parts).strip()


def _render(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None or value == "" or value == [] or value == {}:
        return ""
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "; ".join(filter(None, (_render(v) for v in value)))
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_render(v)}" for k, v in value.items() if _render(v))
    return str(value)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def iter_json_files(root: Path) -> Iterator[Path]:
    """Все *.json файлы рекурсивно; только файлы (некоторые «папки» имеют расширение .json)."""
    for path in sorted(root.rglob("*.json")):
        if path.is_file():
            yield path


def _flatten(items: list[Any]) -> Iterator[Any]:
    """Обходит возможные вложенные списки (United.json и merged.json содержат list[list])."""
    for item in items:
        if isinstance(item, list):
            yield from _flatten(item)
        else:
            yield item


def load_concepts(root: Path, max_file_size_mb: int = 10) -> LoadReport:
    root = Path(root)
    report = LoadReport()
    limit_bytes = max_file_size_mb * 1024 * 1024

    for path in iter_json_files(root):
        report.files_scanned += 1
        rel = str(path.relative_to(root))
        try:
            size = path.stat().st_size
            if size > limit_bytes:
                raise ValueError(f"файл больше лимита {max_file_size_mb} МБ ({size} Б)")
            raw = path.read_text(encoding="utf-8-sig")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                # В базе встречаются файлы с реальными переводами строк внутри строк —
                # повторная попытка в нестрогом режиме спасает такие документы.
                data = json.loads(raw, strict=False)
        except Exception as exc:  # noqa: BLE001 - файл не должен ронять всю индексацию
            log.warning("Пропущен файл %s: %s", rel, exc)
            report.errors.append({"file": rel, "error": f"{type(exc).__name__}: {exc}"})
            continue

        if isinstance(data, dict):  # допустим одиночный концепт в файле
            data = [data]
        if not isinstance(data, list):
            log.warning("Пропущен файл %s: ожидался список объектов", rel)
            report.errors.append({"file": rel, "error": "структура JSON не является списком объектов"})
            continue

        report.files_ok += 1
        seen_in_file: dict[str, int] = {}
        for idx, item in enumerate(_flatten(data)):
            if not isinstance(item, dict):
                report.errors.append({"file": rel, "error": f"элемент #{idx} не является объектом"})
                continue
            cid = str(item.get("id") or "").strip() or f"{Path(rel).stem}#{idx}"
            # уникальный concept_id внутри файла (дубли "id" в одном файле допускаются)
            n = seen_in_file.get(cid, 0)
            seen_in_file[cid] = n + 1
            unique_cid = cid if n == 0 else f"{cid}~{n}"
            payload_json = canonical_json(item)
            report.concepts.append(
                Concept(
                    source_path=rel,
                    concept_id=unique_cid,
                    title=item.get("title") if isinstance(item.get("title"), str) else None,
                    category=item.get("category") if isinstance(item.get("category"), str) else None,
                    payload=item,
                    content_hash=sha256_hex(payload_json),
                    text=build_embedding_text(item),
                )
            )

    log.info(
        "Загружено %d концептов из %d/%d файлов (ошибок: %d)",
        len(report.concepts), report.files_ok, report.files_scanned, len(report.errors),
    )
    return report
