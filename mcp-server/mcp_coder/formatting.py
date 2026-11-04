"""Чистые текстовые преобразования: обрезка, нумерация, diff, патчи, таблицы.

Core-слой: ни одна функция не трогает файловую систему и сеть. Весь «ум» о
представлении вывода живёт здесь и покрыт юнит-тестами, а адаптеры
(tools_*.py) занимаются только вводом-выводом.

Зачем это нужно экономически: самый дорогой ресурс агента — окно контекста.
Инструмент, вернувший 300 КБ логов целиком, стоит денег и качества рассуждений.
Поэтому каждый вывод проходит через явные потолки и всегда сообщает, что было
отброшено — агент должен понимать, что ему показали не всё, и уметь запросить
остальное.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence


# ===========================================================================
# Байты и символы: единая обрезка
# ===========================================================================
def clamp(text: str, max_chars: int, *, tail: bool = False) -> tuple[str, int]:
    """Обрезает строку до ``max_chars``; возвращает (текст, сколько отброшено).

    ``tail=True`` — оставляем хвост (важно для логов: свежие строки в конце).
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text, 0
    dropped = len(text) - max_chars
    if tail:
        return text[-max_chars:], dropped
    return text[:max_chars], dropped


def truncate_out(text: str, max_chars: int) -> str:
    """Потолок для «плотного» вывода (diff, grep, дерево) — с пометкой."""
    kept, dropped = clamp(text, max_chars)
    if dropped:
        kept += f"\n... [truncated {dropped} chars]"
    return kept


def decode(raw: bytes | str | None) -> str:
    """Безопасное декодирование байтов из Docker/subprocess в текст."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    return raw.decode("utf-8", errors="replace")


def cap_bytes(parts: Sequence[str], max_bytes: int) -> tuple[str, bool]:
    """Суммарный потолок в байтах для нескольких потоков (stdout+stderr).

    Возвращает (склейка, was_truncated). Режется по байтам, а не по символам:
    docker API отдаёт байты, а многобайтовые последовательности дороже бюджета.
    """
    joined = "\n".join(part for part in parts if part)
    encoded = joined.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return joined, False
    return encoded[:max_bytes].decode("utf-8", errors="replace"), True


def human_bytes(num: int | None) -> str:
    if num is None:
        return "?"
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}TiB"


# ===========================================================================
# Поканионное чтение файла: нумерованные строки
# ===========================================================================
@dataclass(frozen=True)
class LineSlice:
    """Окно строк файла + метаданные для «карты» контекста."""

    text: str
    total_lines: int
    first_line: int
    last_line: int
    truncated_by_bytes: bool = False
    truncated_by_lines: bool = False
    dropped_tail_lines: int = 0

    @property
    def header(self) -> str:
        if not self.total_lines:
            return "empty file"
        span = f"lines {self.first_line}-{self.last_line}"
        if not (self.truncated_by_bytes or self.truncated_by_lines):
            return f"{span} of {self.total_lines}"
        return (
            f"{span} of {self.total_lines} "
            f"[PARTIAL: {self.dropped_tail_lines} line(s) not shown — "
            f"continue with start_line={self.last_line + 1}]"
        )


def split_lines(content: str) -> list[str]:
    """Разбивает на строки, различая «пустой файл» и «одна пустая строка»."""
    if content == "":
        return []
    return content.split("\n")


def number_lines(lines: Sequence[str], start: int) -> str:
    """``cat -n``-подобная нумерация: '  12 | код'.

    Номера нужны агенту, чтобы ссылаться на код и делать точечные правки.
    Ширина колонки выравнивается по последнему номеру.
    """
    if not lines:
        return ""
    width = max(4, len(str(start + len(lines) - 1)))
    return "\n".join(
        f"{str(start + offset).rjust(width)} | {line.rstrip(chr(13) + chr(10))}"
        for offset, line in enumerate(lines)
    )


def build_slice(
    content: str,
    *,
    start_line: int = 0,
    end_line: int = 0,
    max_lines: int,
    max_chars: int,
) -> LineSlice:
    """Выбирает диапазон строк (1-based, включительно) и применяет потолки.

    При переполнении по символам режем *конец* окна, а не его середину наугад:
    иначе агент теряет начало файла, которое чаще всего и нужно (импорты,
    сигнатуры). Считаем реально показанные строки по количеству переводов.
    """
    lines = split_lines(content)
    total = len(lines)
    first = max(1, start_line) if start_line else 1
    last = min(total, end_line) if end_line else total
    if total and first > total:
        first = last = total
    elif last < first:
        last = first - 1

    window = lines[first - 1 : last]
    by_lines = bool(max_lines) and len(window) > max_lines
    if by_lines:
        window = window[:max_lines]

    kept, dropped_chars = clamp(number_lines(window, first), max_chars)
    shown_lines = kept.count("\n") + 1 if kept else 0
    dropped_tail = max(0, len(lines) - first + 1 - shown_lines)

    return LineSlice(
        text=kept,
        total_lines=total,
        first_line=first,
        last_line=first + shown_lines - 1 if shown_lines else first - 1,
        truncated_by_bytes=bool(dropped_chars),
        truncated_by_lines=by_lines,
        dropped_tail_lines=dropped_tail,
    )


# ===========================================================================
# Diff
# ===========================================================================
def unified_diff(old: str, new: str, path: str, *, context: int = 3, max_hunks: int = 40) -> str:
    """Дифф до/после — главный инструмент самопроверки агента.

    Без diff агент, правящий файл вслепую, не видит побочных эффектов замены;
    с diff он замечает обрезанную скобку за один ход вместо цикла «правка —
    упавший тест».
    """
    chunks = list(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=context,
        )
    )
    if not chunks:
        return ""
    kept: list[str] = []
    hunks = 0
    for line in chunks:
        if line.startswith("@@"):
            hunks += 1
            if hunks > max_hunks:
                kept.append(f"... [diff truncated after {max_hunks} hunks]\n")
                break
        kept.append(line if line.endswith("\n") else line + "\n")
    return "".join(kept)


def diff_stats(old: str, new: str) -> tuple[int, int]:
    """(added, removed) — компактная сводка без тела диффа."""
    matcher = difflib.SequenceMatcher(a=old.splitlines(), b=new.splitlines())
    added = removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            added += j2 - j1
        elif tag == "delete":
            removed += i2 - i1
        elif tag == "replace":
            added += j2 - j1
            removed += i2 - i1
    return added, removed


# ===========================================================================
# Патч: последовательные замены (multi-edit)
# ===========================================================================
@dataclass
class Edit:
    """Одна замена внутри файла."""

    old_text: str
    new_text: str
    replace_all: bool = False


@dataclass
class PatchReport:
    text: str
    per_edit: list[int] = field(default_factory=list)

    @property
    def applied(self) -> int:
        return len(self.per_edit)


class PatchError(ValueError):
    """Фрагмент не найден или найден неоднозначно — файл не меняется."""


def apply_edits(content: str, edits: Iterable[Edit]) -> PatchReport:
    """Применяет замены последовательно; атомарно (всё или ничего).

    Последовательность существенна: второй edit часто правит результат первого.
    Ошибка на любом шаге — полный откат, потому что частичный патч хуже
    отсутствия патча (код в полу-состоянии).
    """
    text = content.replace("\r\n", "\n")
    report = PatchReport(text=text)
    for index, edit in enumerate(edits, 1):
        old = edit.old_text.replace("\r\n", "\n")
        new = edit.new_text.replace("\r\n", "\n")
        if not old:
            raise PatchError(f"edit #{index}: пустой old_text — замена не определена.")
        count = text.count(old)
        if count == 0:
            raise PatchError(
                f"edit #{index}: фрагмент не найден (0 совпадений). "
                f"Включите в old_text 1-2 соседние строки, чтобы задали контекст."
            )
        if count > 1 and not edit.replace_all:
            raise PatchError(
                f"edit #{index}: фрагмент встречается {count} раз. "
                f"Добавьте контекст в old_text или поставьте replace_all=true."
            )
        text = text.replace(old, new)
        report.per_edit.append(count)
    report.text = text
    return report


# ===========================================================================
# Поисковый вывод
# ===========================================================================
def format_grep_hit(
    rel_path: str,
    line_no: int,
    line: str,
    *,
    max_line_chars: int = 240,
    before: Sequence[str] = (),
    after: Sequence[str] = (),
) -> str:
    """Строка результата поиска: 'path:12: текст' + опциональный контекст."""
    def trim(value: str) -> str:
        body = value.rstrip("\r\n")
        return body if len(body) <= max_line_chars else body[:max_line_chars] + "…"

    rows = [f"{rel_path}:{offset}- {trim(prev)}" for offset, prev in
            ((line_no - len(before) + i, v) for i, v in enumerate(before))]
    rows.append(f"{rel_path}:{line_no}: {trim(line)}")
    rows.extend(
        f"{rel_path}:{line_no + i}- {trim(nxt)}" for i, nxt in enumerate(after, 1)
    )
    return "\n".join(rows)


def match_line_numbers(
    lines: Sequence[str],
    pattern: str,
    *,
    ignore_case: bool = False,
    regex: bool = False,
    whole_word: bool = False,
) -> list[int]:
    """0-based индексы совпавших строк.

    Невалидная регулярка всплывает как ``re.error`` наружу, а не молчаливый
    ноль совпадений: агент должен починить паттерн, а не искать «в пустоте».
    """
    hits: list[int] = []
    if regex:
        compiled = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        return [i for i, line in enumerate(lines) if compiled.search(line)]
    needle = pattern.lower() if ignore_case else pattern
    for index, line in enumerate(lines):
        hay = line.lower() if ignore_case else line
        if whole_word:
            if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", hay):
                hits.append(index)
        elif needle in hay:
            hits.append(index)
    return hits


# ===========================================================================
# Таблицы (SQL, контейнеры)
# ===========================================================================
def render_table(
    headers: Sequence[str], rows: Sequence[Sequence[object]], *, max_cell: int = 60
) -> str:
    """ASCII-таблица фиксированной ширины.

    Выровненная сетка читается моделью лучше CSV: колонки сохраняют позиции и
    не «плывут» на переносе строк.
    """
    def cell(value: object) -> str:
        if value is None:
            return "NULL"
        text = str(value).replace("\n", "\\n").replace("\t", " ")
        return text if len(text) <= max_cell else text[: max_cell - 1] + "…"

    header_cells = [cell(h) for h in headers]
    body = [[cell(v) for v in row] for row in rows]
    widths = [len(h) for h in header_cells]
    for row in body:
        for i, value in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(value))
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def fmt(row: Sequence[str]) -> str:
        return "| " + " | ".join(v.ljust(w) for v, w in zip(row, widths)) + " |"

    return "\n".join([sep, fmt(header_cells), sep, *(fmt(r) for r in body), sep])


def join_kv(pairs: Iterable[tuple[str, object]], *, sep: str = "  ") -> str:
    """Компактная однострочная сводка: 'service=api  state=running'."""
    return sep.join(f"{key}={value}" for key, value in pairs if value not in (None, ""))


def paginate_note(shown: int, total: int, unit: str = "items", *, arg: str = "offset") -> str:
    """Честная пометка о пагинации — подсказывает, каким параметром брать дальше."""
    if total <= shown:
        return ""
    return f"[shown {shown}/{total} {unit}; next page: {arg}={shown}]"
