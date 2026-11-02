#!/usr/bin/env python3
"""Сборщик единой базы знаний: обходит ВСЕ подпапки knowledge_base, проверяет
структуру JSON-объектов и собирает всё в один файл ``kb_all.json``.

Зачем: приложение индексирует только папки «Общий json» (см. app/services/kb_reader.py),
поэтому файлы, лежащие в других подпапках, в БД не попадали. Этот скрипт объединяет
все валидные концепты со всей базы знаний в один JSON, который можно индексировать
целиком (в приложении укажите COMMON_DIR_NAMES=[] или KB_ROOT=/app/knowledge_base_merged).

Формат результата — плоский список объектов-концептов: [{"id": ..., "title": ...}, ...]

Структура концепта (проверка):
  обязательные поля : id (или name/title — см. --require-fields), title
  рекомендуемые     : category, essence, formula, interpretation, sector_specifics,
                      limitations, related_concepts, search_keywords, source_text_excerpt

Использование (из любой папки, пути разрешаются относительно скрипта):
    python3 build_kb.py                    # собрать kb_all.json + отчёт
    python3 build_kb.py --check            # только проверка структуры, без записи
    python3 build_kb.py --strict           # битые JSON = ненулевой код возврата
    python3 build_kb.py --output merged.json --dedup id+hash --fix-control-chars

Код возврата: 0 — успех; 1 — ошибки (--strict и есть битые файлы); 2 — ошибка аргументов/пути.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "kb_all.json"
REQUIRED_FIELDS_DEFAULT = ("id", "title")
RECOMMENDED_FIELDS = (
    "category", "essence", "formula", "interpretation", "sector_specifics",
    "limitations", "related_concepts", "search_keywords", "source_text_excerpt",
)


# ------------------------------ чтение файлов -------------------------------
def load_json(path: Path, *, fix_control_chars: bool) -> Any:
    """Читает JSON с utf-8-sig (BOM); опционально чинит управляющие символы внутри строк.

    Строгие парсеры (python json, PostgreSQL jsonb) отвергают raw \n/\t/" inside
    строковых литералов — такие файлы правятся заменой на экранированные последовательности.
    """
    text = path.read_text(encoding="utf-8-sig")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if not fix_control_chars:
            raise
        fixed = _escape_control_chars_in_strings(text)
        obj = json.loads(fixed)  # если и после починки не читается — бросаем
        print(f"    [FIX] {path.name}: исправлены недопустимые управляющие символы в строках")
        return obj


def _escape_control_chars_in_strings(text: str) -> str:
    """Экранирует управляющие символы, находящиеся ВНУТРИ JSON-строк (вне строк не трогает)."""
    out: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
                out.append(ch)
                continue
            if ch == "\\":
                escaped = True
                out.append(ch)
                continue
            if ch == '"':
                in_string = False
                out.append(ch)
                continue
            if ch in ("\n", "\r", "\t") or unicodedata.category(ch) == "Cc":
                out.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}.get(
                    ch, f"\\u{ord(ch):04x}"))
                continue
            out.append(ch)
        else:
            if ch == '"':
                in_string = True
            out.append(ch)
    return "".join(out)


# ------------------------------ обход структуры -----------------------------
def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def extract_concepts(raw: Any) -> list[dict[str, Any]]:
    """Рекурсивно находит все словари-концепты (с обязательными id+title), любая вложенность."""
    found: list[dict[str, Any]] = []

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
    return found


def validate_obj(obj: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    """Возвращает список замечаний к объекту-концепту (пусто = всё в порядке)."""
    problems: list[str] = []
    for field in required:
        if field not in obj:
            problems.append(f"нет обязательного поля '{field}'")
        elif not str(obj[field]).strip():
            problems.append(f"поле '{field}' пустое")
    missing_recommended = [f for f in RECOMMENDED_FIELDS if f not in obj]
    if missing_recommended:
        problems.append("нет рекомендуемых полей: " + ", ".join(missing_recommended))
    return problems


# --------------------------------- сборка -----------------------------------
def build(root: Path, args: argparse.Namespace) -> int:
    if not root.is_dir():
        print(f"[ERR] Каталог не найден: {root}", file=sys.stderr)
        return 2

    json_files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".json")
    # сам результат и служебные файлы не должны участвовать в следующем прогоне
    out_path = Path(args.output).resolve()
    skip_names = {"desktop.ini", out_path.name, "build_kb_report.json"}
    json_files = [p for p in json_files if p.name not in skip_names]

    print(f"Корень базы знаний : {root}")
    print(f"Найдено .json      : {len(json_files)}")
    print("-" * 72)

    all_concepts: list[dict[str, Any]] = []
    seen_content: set[str] = set()
    seen_ids: dict[str, str] = {}
    files_ok = files_bad = concepts_total = dup_content = dup_id = 0
    bad_files: list[tuple[str, str]] = []
    empty_files: list[str] = []
    warnings: list[tuple[str, list[str]]] = []

    for path in json_files:
        rel = str(path.relative_to(root))
        try:
            raw = load_json(path, fix_control_chars=args.fix_control_chars)
        except json.JSONDecodeError as exc:
            files_bad += 1
            msg = f"{exc.msg} (line {exc.lineno}, col {exc.colno})"
            bad_files.append((rel, msg))
            print(f"[BAD ] {rel}\n        невалидный JSON: {msg}")
            continue
        except Exception as exc:  # noqa: BLE001
            files_bad += 1
            bad_files.append((rel, f"{exc.__class__.__name__}: {exc}"))
            print(f"[BAD ] {rel}\n        ошибка чтения: {bad_files[-1][1]}")
            continue

        objs = extract_concepts(raw)
        if not objs:
            empty_files.append(rel)
            print(f"[EMPTY] {rel} — нет объектов с полями id+title (type={type(raw).__name__})")
            continue

        added = skipped_c = skipped_i = 0
        file_problems: list[str] = []
        for obj in objs:
            problems = validate_obj(obj, tuple(args.require_fields.split(",")))
            if problems:
                oid = obj.get('id', '?')
                oid = oid if isinstance(oid, str) else canonical_json(oid)[:40]
                file_problems.append(f"  объект id={oid}: " + "; ".join(problems))

            digest = content_hash(obj)
            if digest in seen_content:
                skipped_c += 1
                dup_content += 1
                continue
            cid = str(obj.get("id", ""))
            if cid and cid in seen_ids and not args.allow_dup_ids:
                skipped_i += 1
                dup_id += 1
                file_problems.append(f"  дубль id='{cid}' (уже из: {seen_ids[cid]})")
                continue
            seen_content.add(digest)
            if cid:
                seen_ids[cid] = rel
            enriched = dict(obj)
            enriched.setdefault("_source", rel)
            all_concepts.append(enriched)
            added += 1

        files_ok += 1
        concepts_total += len(objs)
        status = "[OK  ]" if not file_problems else "[WARN]"
        print(f"{status} {rel}: концептов={len(objs)}, добавлено={added}, "
              f"дублей_содержимого={skipped_c}, дублей_id={skipped_i}")
        for line in file_problems:
            if "рекомендуемых" not in line or args.strict_schema:
                print("       " + line)
        if file_problems:
            warnings.append((rel, file_problems))

    print("-" * 72)
    print(f"Итог: файлов OK={files_ok}, битых={files_bad}, пустых={len(empty_files)}; "
          f"концептов найдено={concepts_total}, уникальных собрано={len(all_concepts)} "
          f"(отфильтровано: дублей содержимого={dup_content}, дублей id={dup_id})")

    report = {
        "kb_root": str(root),
        "files_scanned": len(json_files),
        "files_ok": files_ok,
        "files_invalid_json": bad_files,
        "files_without_concepts": empty_files,
        "concepts_found": concepts_total,
        "concepts_written": len(all_concepts),
        "duplicates_content": dup_content,
        "duplicates_id": dup_id,
        "ids_used_by_sections": Counter(
            c["_source"].split("/")[0] for c in all_concepts
        ).most_common(),
    }

    if args.check:
        print("--check: ничего не записано.")
        return finish_code(args, bad_files)

    if not all_concepts:
        print("[ERR] собирать нечего — проверьте вывод выше.", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(all_concepts, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    tmp.replace(out_path)
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"[WRITE] {out_path} ({size_mb:.1f} MiB, {len(all_concepts)} концептов)")

    report_path = out_path.with_name(out_path.stem + "_report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[WRITE] {report_path} (отчёт: битые файлы, дубли, разбивка по разделам)")
    return finish_code(args, bad_files)


def finish_code(args: argparse.Namespace, bad_files: list[tuple[str, str]]) -> int:
    if bad_files and args.strict:
        print(f"[STRICT] {len(bad_files)} битых файл(ов) — код возврата 1", file=sys.stderr)
        return 1
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(SCRIPT_DIR),
                        help="папка knowledge_base (по умолчанию — где лежит сам скрипт)")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT),
                        help="куда писать объединённый JSON (по умолчанию knowledge_base/kb_all.json)")
    parser.add_argument("--check", action="store_true", help="только проверка, без записи файла")
    parser.add_argument("--strict", action="store_true",
                        help="битые JSON -> код возврата 1; предупреждения о структуре считать ошибками")
    parser.add_argument("--strict-schema", action="store_true",
                        help="печатать замечания и про отсутствующие РЕКОМЕНДУЕМЫЕ поля тоже")
    parser.add_argument("--allow-dup-ids", action="store_true",
                        help="не отбрасывать концепты с повторяющимся id (дубли содержимого отсекаются всегда)")
    parser.add_argument("--require-fields", default=",".join(REQUIRED_FIELDS_DEFAULT),
                        help="список обязательных полей через запятую (default: id,title)")
    parser.add_argument("--fix-control-chars", action="store_true",
                        help="автопочинка недопустимых управляющих символов внутри строк JSON")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args(sys.argv[1:])
    return build(Path(args.root).resolve(), args)


if __name__ == "__main__":
    sys.exit(main())
