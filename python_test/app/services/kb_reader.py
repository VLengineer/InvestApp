"""Чтение knowledge_base: только «общие» JSON (папка ``Общий json`` на любой глубине).

Паттерн: Strategy — политика выбора файлов вынесена в отдельный метод, чтобы её
можно было заменить (например, на глобальный поиск всех *.json) без правды в остальном коде.
Все операции с файлами выполняются в thread pool, чтобы не блокировать event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Iterable

from app.core.exceptions import KnowledgeBaseError
from app.services.domain import Concept, SourceFile, extract_concepts

logger = logging.getLogger(__name__)

_JSON_SUFFIXES = {".json"}


class KnowledgeBaseReader:
    def __init__(
        self,
        kb_root: Path | str,
        *,
        common_dir_names: Iterable[str] = ("Общий json",),
        max_chunk_chars: int = 8_000,
        max_file_bytes: int = 20 * 1024 * 1024,
    ) -> None:
        self._kb_root = Path(kb_root).resolve()
        self._common_dir_names = tuple(name.strip().lower() for name in common_dir_names if name.strip())
        self._max_chunk_chars = max_chunk_chars
        self._max_file_bytes = max_file_bytes

    # ------------------------------ выбор файлов ----------------------------
    def _is_common_json(self, path: Path) -> bool:
        """Файл .json, лежащий внутри папки с именем «Общий json» (любая глубина)."""
        if path.suffix.lower() not in _JSON_SUFFIXES:
            return False
        parents = {p.name.lower() for p in path.relative_to(self._kb_root).parts[:-1]}
        return any(name in parents for name in self._common_dir_names)

    def discover_files(self) -> list[Path]:
        if not self._kb_root.is_dir():
            raise KnowledgeBaseError(f"Каталог knowledge_base не найден: {self._kb_root}")
        files: list[Path] = []
        for path in sorted(self._kb_root.rglob("*")):
            if not path.is_file():
                continue
            # защита от path traversal / симлинков за пределы базы знаний
            resolved = path.resolve()
            if not resolved.is_relative_to(self._kb_root):
                logger.warning("Пропущен файл вне knowledge_base: %s", path)
                continue
            if resolved.name == "desktop.ini":
                continue
            if self._is_common_json(resolved):
                files.append(resolved)
        return files

    # -------------------------------- чтение --------------------------------
    def _read_one_sync(self, path: Path) -> SourceFile:
        rel_path = str(path.relative_to(self._kb_root))
        source = SourceFile(path=path, rel_path=rel_path)
        try:
            size = path.stat().st_size
            if size > self._max_file_bytes:
                raise KnowledgeBaseError(f"Файл слишком большой ({size} байт): {rel_path}")
            raw: Any = json.loads(path.read_text(encoding="utf-8-sig"))
            source.concepts = extract_concepts(raw, rel_path=rel_path, max_chunk_chars=self._max_chunk_chars)
            if not source.concepts:
                source.error = "не найдено ни одного концепта с полями id+title"
        except json.JSONDecodeError as exc:
            source.error = f"невалидный JSON: {exc.msg} (line {exc.lineno}, col {exc.colno})"
        except Exception as exc:  # noqa: BLE001 - один битый файл не должен ронять индексацию
            source.error = f"ошибка чтения: {exc.__class__.__name__}: {exc}"
        return source

    async def load(self) -> list[SourceFile]:
        """Возвращает содержимое всех общих JSON-файлов."""
        files = self.discover_files()
        if not files:
            raise KnowledgeBaseError(
                f"В {self._kb_root} нет ни одного «общего» JSON (ожидаемая папка: "
                f"{', '.join(self._common_dir_names)})"
            )
        logger.info("Найдено общих JSON-файлов: %d", len(files))
        sources = await asyncio.gather(*(asyncio.to_thread(self._read_one_sync, f) for f in files))
        for source in sources:
            if source.error:
                logger.warning("Файл %s пропущен: %s", source.rel_path, source.error)
        return list(sources)

    async def flatten_concepts(self) -> tuple[list[Concept], list[SourceFile]]:
        sources = await self.load()
        concepts: list[Concept] = []
        for source in sources:
            concepts.extend(source.concepts)
        return concepts, sources
