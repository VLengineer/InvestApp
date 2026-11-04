"""Политики безопасности: пути, shell-команды, SQL, маскировка секретов.

Core-слой (Clean Architecture): чистые функции без I/O за исключением тех,
где I/O и есть суть операции (атомарная запись). Ни один адаптер не дублирует
эти правила — все вызовы проходят через единые guard'ы (DRY, единая точка
аудита).

Ключевые отличия от наивной реализации ``os.path.join(root, path)`` + чёрный
список подстрок:

1. ``os.path.join`` молча выбрасывает левый аргумент при абсолютном пути,
   поэтому ``/etc/passwd`` становился доступным как есть.
2. ``..`` надо нейтрализовать *до* проверки защищённых сегментов, иначе
   ``../.git/config`` обходит фильтр.
3. Чёрный список подстрок ломает легитимные команды (``python -c "import
   docker"``) и не защищает от обхода (``rm${IFS}-rf``), поэтому используется
   белый список бинарей + структурный разбор команды.
"""

from __future__ import annotations

import os
import re
import shlex
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .config import Settings

# Операторы, по которым shell-строка раскладывается на сегменты.
_SHELL_BREAK_OPS: Final = frozenset({"|", "||", "&&", ";", "&", "|&"})
# Программы-обёртки, которые сами по себе безобидны: проверяем вложенную команду.
_WRAPPER_PREFIXES: Final = frozenset({"env", "nohup", "nice", "stdbuf", "timeout"})
# Разрешённые цели перенаправления вне рабочей директории.
_ALLOWED_REDIRECT_TARGETS: Final = frozenset(
    {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/fd/1", "/dev/fd/2"}
)
# Конструкциям вида ``$(...)``/`` `...` `` здесь не место: это скрытое выполнение.
_FORBIDDEN_SYNTAX: Final = (
    (r"\$\(", "command substitution $(...)"),
    (r"`", "backtick command substitution"),
    (r"\$\{[^}]*IFS[^}]*\}", "IFS injection"),
    (r"\$\{[A-Za-z_][A-Za-z0-9_]*:?", "parameter expansion (variable interpolation)"),
    (r"\beval\b", "eval"),
    (r"\bxargs\b[^|]*\b(sh|bash)\b", "xargs piping into a shell"),
)
# Запрещённые цели перенаправления (устройство, procfs, запись в чужой fd).
_DANGEROUS_PATHS: Final = (
    "/proc/self/environ",
    "/proc/self/cmdline",
    "/proc/sys",
    "/dev/tcp",
    "/dev/udp",
)
_TIME_UNITS: Final = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86_400.0}


class PathError(ValueError):
    """Запрошенный путь нарушает файловую политику или недоступен."""


class CommandDenied(ValueError):
    """Команда отклонена политикой выполнения."""


@dataclass(frozen=True)
class ResolvedPath:
    """Канонический вид пути после применения файловой политики.

    key     — стабильный идентификатор для ответов API и кэша;
    rel     — путь относительно рабочей директории (для читаемого вывода),
              ``None`` если файл лежит вне неё;
    protected — сегмент защищённой директории, если путь в неё попадает.
    """

    requested: str
    resolved: Path
    key: str
    rel: str | None
    inside_workspace: bool
    protected: str | None
    exists: bool
    is_dir: bool
    is_file: bool
    size: int | None
    modified_at: float | None

    @property
    def exists_ok(self) -> bool:
        return self.exists


class PathPolicy:
    """Файловая политика проекта: containment + симлинки + защищённые сегменты."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._root = Path(settings.workspace_dir).resolve(strict=False)
        self._protected = frozenset(
            part.strip().lower() for part in settings.protected_dirs if part.strip()
        )

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------ utils
    def _relative_parts(self, resolved: Path) -> tuple[str, ...]:
        try:
            return resolved.relative_to(self._root).parts
        except ValueError:
            return ()

    def _find_protected(self, resolved: Path) -> str | None:
        """Ищет защищённый сегмент по *всему* пути, а не только по первому.

        Прежняя реализация проверяла ``parts[0]`` и пропускала
        ``backend-frontend/.git/config``.
        """
        candidates = list(resolved.parts)
        for segment in candidates:
            if segment.lower() in self._protected:
                return segment
        return None

    def find_protected_in_rel(self, rel_path: str) -> str | None:
        """Проверка запрошенного пути «как есть» — до канонизации симлинков."""
        for part in Path(rel_path).parts:
            if part in {".", ".."}:
                continue
            if part.lower() in self._protected:
                return part
        return None

    def to_rel(self, resolved: Path) -> str | None:
        parts = self._relative_parts(resolved)
        return "/".join(parts) if parts else ""

    def to_key(self, resolved: Path) -> str:
        rel = self.to_rel(resolved)
        return rel if rel is not None else resolved.as_posix()

    # ----------------------------------------------------------------- resolve
    def resolve(
        self,
        path: str | os.PathLike[str] | None,
        *,
        must_exist: bool = False,
        for_write: bool = False,
        allow_outside: bool = True,
        must_be: str | None = None,
    ) -> ResolvedPath:
        """Канонизирует путь и применяет политику. Бросает ``PathError`` при отказе.

        ``must_be``: ``"file"`` | ``"dir"`` | ``None``.
        """
        raw = "" if path is None else str(path).strip()
        requested = raw or "."

        # Нормализуем разделители и убираем ведущий './' — иначе «./../x» обходит фильтр.
        candidate = Path(raw.replace("\x00", ""))
        if not candidate.is_absolute():
            candidate = self._root / candidate

        # resolve(strict=False) схлопывает '..' и разворачивает симлинки; для
        # несуществующего пути канонизирует лексически по существующим родителям.
        resolved = candidate.resolve(strict=False)

        rel_parts = self._relative_parts(resolved)
        inside = bool(rel_parts) or resolved == self._root
        protected = self._find_protected(resolved)

        if protected is not None:
            raise PathError(
                f"Путь '{requested}' ведёт в защищённую директорию '{protected}'. "
                f"Доступ запрещён политикой ({', '.join(sorted(self._protected))})."
            )

        if not inside and not allow_outside:
            raise PathError(
                f"Путь '{requested}' resolves в '{resolved}' вне рабочей директории "
                f"'{self._root}'. Операции разрешены только внутри проекта."
            )

        if for_write:
            self._assert_writable(resolved, requested)

        exists = resolved.exists()
        if must_exist and not exists:
            raise PathError(f"Путь не найден: '{requested}' (resolved: {resolved})")

        is_dir = exists and resolved.is_dir()
        is_file = exists and resolved.is_file()
        if must_be == "file" and exists and not is_file:
            raise PathError(f"Ожидался файл, а получен каталог: '{requested}'")
        if must_be == "dir" and exists and not is_dir:
            raise PathError(f"Ожидался каталог, а получен файл: '{requested}'")

        size: int | None = None
        mtime: float | None = None
        if is_file:
            try:
                stat = resolved.stat()
                size, mtime = stat.st_size, stat.st_mtime
            except OSError:
                size = mtime = None

        return ResolvedPath(
            requested=requested,
            resolved=resolved,
            key=self.to_key(resolved),
            rel=self.to_rel(resolved),
            inside_workspace=inside,
            protected=None,
            exists=exists,
            is_dir=is_dir,
            is_file=is_file,
            size=size,
            modified_at=mtime,
        )

    def _assert_writable(self, resolved: Path, requested: str) -> None:
        """Запись только внутри проекта: запись наружу — это побег из песочницы."""
        if resolved == self._root:
            raise PathError("Нельзя перезаписать корень рабочей директории.")
        if not self._relative_parts(resolved):
            raise PathError(
                f"Запись по пути '{requested}' невозможна: цель лежит вне "
                f"рабочей директории ({self._root})."
            )
        # Родитель тоже обязан остаться внутри — иначе «dir/../../../tmp/x».
        parent = resolved.parent
        if not self._relative_parts(parent) and parent != self._root:
            raise PathError(f"Родительский каталог '{parent}' вне рабочей директории.")

    def guard_for_write(self, path: str) -> ResolvedPath:
        """Проверяет запись в ``path`` или, для несуществующего пути, в его родителей."""
        try:
            return self.resolve(path, for_write=True)
        except PathError:
            parent = str(Path(path).parent)
            if parent in ("", "."):
                raise
            self.resolve(parent, must_exist=True, must_be="dir", for_write=True)
            raise

    # ------------------------------------------------------------------- write
    def atomic_write(self, resolved: ResolvedPath, content: str) -> tuple[int, float]:
        """Атомарная запись: temp-файл в той же директории + ``os.replace``.

        Прерванный посреди записи файл больше не оставляет проект в
        полу-состоянии (раньше ``open(w)`` trunc'ал файл до crash).
        Возвращает (байт_на_диске, mtime).
        """
        target = resolved.resolved
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = content.encode("utf-8")
        fd, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        stat = target.stat()
        return stat.st_size, stat.st_mtime


# ===========================================================================
# Shell-политика
# ===========================================================================
@dataclass(frozen=True)
class CommandSegment:
    """Один сегмент конвейера: аргументы после разделения по ``|``/``;``/``&&``."""

    argv: tuple[str, ...]

    @property
    def program(self) -> str | None:
        for arg in self.argv:
            if _ENV_ASSIGN_RE.match(arg):
                continue
            return Path(arg).name
        return None

    @property
    def is_env_assignment(self) -> bool:
        return bool(self.argv) and all(_ENV_ASSIGN_RE.match(a) for a in self.argv)


@dataclass(frozen=True)
class CommandPlan:
    """Результат структурной валидации shell-команды."""

    command: str
    segments: tuple[CommandSegment, ...]
    timeout: float
    env: dict[str, str]

    @property
    def programs(self) -> tuple[str, ...]:
        return tuple(s.program for s in self.segments if s.program)


#: ``VAR=value cmd`` — префикс окружения, program берётся после него.
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

#: ``2>&1`` — склейка дескрипторов: это не program и не path-аргумент.
#: Проверяется с конца токена, чтобы ``&&`` не съесть раньше времени.
_REDUPLICATIVES = frozenset({"&1", "&2", "1&2", "2&1"})

#: Операторы, после которых обязана идти следующая команда.
#: ``|&`` (bash: stdout+stderr) нормализуется в ``|`` за счёт ``&`` в префиксах.
_OPERATOR_PREFIXES: tuple[str, ...] = (
    "||", "&&", "|&", "\n", ";", "&", "|",
)

#: Что можно вставить между оператором и следующим токеном, не прерывая команду.
_WHITESPACE = " \t\r"


def _split_shell(raw: str) -> tuple[tuple[bool, list[str]], ...]:
    """Токенизирует shell-строку с учётом кавычек — то, чего не делает ``shlex``.

    ``shlex.split`` склеивает оператор с соседним токеном, поэтому
    ``echo hi; rm -rf /`` превращался в ``['echo', 'hi;', 'rm', ...]`` — и
    ``rm`` переставал быть программой, т.е. уходил из-под проверки. Кавычки
    защищают симметрично: ``bash -c 'echo; python x'`` остаётся одним токеном.

    Возвращает ``[(is_data, [tokens...]), ...]``: сегменты команд и блоки
    перенаправлений/операторов без программ. Кавычки снимаются, поэтому
    argv эквивалентен тому, что увидит ``sh -c``.
    """
    segments: list[tuple[bool, list[str]]] = []
    current: list[str] = []
    token: list[str] = []
    has_token = False
    quote: str | None = None
    i, n = 0, len(raw)

    def close_token() -> None:
        nonlocal has_token
        if has_token:
            current.append("".join(token))
            token.clear()
            has_token = False

    def flush(is_data: bool) -> None:
        nonlocal current
        close_token()
        if current:
            segments.append((is_data, current))
            current = []

    while i < n:
        char = raw[i]

        if quote:
            if quote == "'" or char != "\\" or quote != '"':
                if char == quote:
                    quote = None
                else:
                    token.append(char)
                    has_token = True
                i += 1
                continue
            if i + 1 < n:  # \-escape внутри двойных кавычек
                token.append(raw[i + 1])
                has_token = True
                i += 2
                continue
            token.append(char)
            has_token = True
            i += 1
            continue

        if char in "'\"":
            quote = char
            has_token = True
            i += 1
            continue

        if char == "\\":
            token.append(char)
            has_token = True
            i += 1
            if i < n:
                token.append(raw[i])
                i += 1
            continue

        if char in _WHITESPACE:
            close_token()
            i += 1
            continue

        operator = next((op for op in _OPERATOR_PREFIXES if raw.startswith(op, i)), None)
        if operator:
            was_data = bool(
                current and (current[-1] in _REDUPLICATIVES or current[-1].startswith(">"))
            )
            flush(was_data)
            i += len(operator)
            # 2-3: «2>» и «>» — один токен, поэтому оператор не должен его резать.
            if operator in ("|", ";", "\n", "&") and i < n and raw[i] in "0123456789<&|":
                ahead = 1 if raw[i].isdigit() else 0
                if i + ahead >= n or raw[i + ahead] not in "<&|":
                    segments.append((False, []))
            continue

        if not has_token and current and current[-1] in _REDUPLICATIVES:
            close_token()
            segments.append((True, current))
            current = []

        token.append(char)
        has_token = True
        i += 1

    flush(bool(current and current[-1] in _REDUPLICATIVES))
    return tuple(segments)


def _scan_operators(command: str) -> tuple[tuple[int, int, str], ...]:
    """Позиции операторов, стоящие *вне* кавычек — для поиска ``$( )`` в env."""
    found: list[tuple[int, int, str]] = []
    quote: str | None = None
    i, n = 0, len(command)
    while i < n:
        char = command[i]
        if quote:
            if char == quote:
                quote = None
            elif char == "\\" and quote == '"' and i + 1 < n:
                i += 1
            i += 1
            continue
        if char in "'\"":
            quote = char
            i += 1
            continue
        if char == "\\":
            i += 2
            continue
        operator = next((op for op in _OPERATOR_PREFIXES if command.startswith(op, i)), None)
        if operator:
            found.append((i, i + len(operator), operator))
            i += len(operator)
            continue
        i += 1
    return tuple(found)


class CommandPolicy:
    """Белый список бинарей + разбор конструкции вместо чёрного списка подстрок."""

    def __init__(self, settings: Settings) -> None:
        self.allow = set(settings.shell_allow) | set(settings.shell_extra_allowed)
        self.deny = set(settings.shell_deny)
        self.default_timeout = settings.exec_default_timeout
        self.max_timeout = settings.exec_max_timeout

    def validate(self, command: str, timeout: float | None = None) -> CommandPlan:
        raw = (command or "").strip()
        if not raw:
            raise CommandDenied("Пустая команда.")
        if len(raw) > 8_000:
            raise CommandDenied("Команда длиннее 8000 символов — слишком сложная для аудита.")
        if "\x00" in raw:
            raise CommandDenied("NUL в команде запрещён.")

        for pattern, reason in _FORBIDDEN_SYNTAX:
            if re.search(pattern, raw):
                raise CommandDenied(
                    f"Конструкция '{reason}' запрещена: исполнительный код должен быть "
                    f"виден целиком (используйте tools_write_file + запуск файла)."
                )

        try:
            tokens = shlex.split(raw, posix=True)
        except ValueError as exc:
            raise CommandDenied(f"Не удалось разобрать команду: {exc}") from exc

        segments = self._split_segments(tokens)
        programs: list[str] = []
        for segment in segments:
            programs.extend(self._check_segment(segment, raw))

        effective_timeout = self._clamp_timeout(timeout)
        return CommandPlan(
            command=raw,
            programs=tuple(dict.fromkeys(programs)),
            timeout=effective_timeout,
            env={},
        )

    # ------------------------------------------------------------- internals
    def _split_segments(self, tokens: list[str]) -> list[list[str]]:
        segments: list[list[str]] = []
        current: list[str] = []
        for token in tokens:
            if token in _SHELL_BREAK_OPS:
                if current:
                    segments.append(current)
                current = []
                continue
            current.append(token)
        if current:
            segments.append(current)
        if not segments:
            raise CommandDenied("Команда пуста после разбора по операторам shell.")
        return segments

    def _check_segment(self, tokens: list[str], raw: str) -> tuple[str, ...]:
        """Возвращает имена исполняемых программ сегмента; бросает при отказе.

        Программой считается только позиция команды: аргументы (`git status` →
        ``status``) не проверяются по белому списку, иначе разбор ломался на
        любой нормальной команде. Для обёрток (``env``, ``timeout``, ``nohup``)
        проверяем вложенную программу.
        """
        cleaned = [t for t in tokens if not self._is_redirection(t)]
        programs: list[str] = []
        index = 0
        while index < len(cleaned):
            token = cleaned[index]
            index += 1
            if token.startswith("-"):
                continue
            # ``FOO=bar cmd`` — присваивание окружения не является программой.
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token):
                continue
            program = Path(token).name  # '/usr/bin/git' -> 'git'
            if program.lower() in self.deny:
                raise CommandDenied(f"Программа '{program}' запрещена политикой выполнения.")
            if program not in self.allow:
                raise CommandDenied(
                    f"Программа '{program}' отсутствует в белом списке "
                    f"({len(self.allow)} разрешённых). Полный список — GET /policy, "
                    f"расширение — MCP_SHELL_ALLOW."
                )
            programs.append(program)
            if program in _WRAPPER_PREFIXES:
                # Пропускаем флаги обёртки, чтобы добраться до вложенной команды.
                while index < len(cleaned) and cleaned[index].startswith("-"):
                    index += 1
                continue
            break  # остальное — аргументы первой программы
        if not programs:
            raise CommandDenied(f"В сегменте не найдено исполняемой программы: {raw!r}")
        self._check_redirections(raw)
        return tuple(programs)

    @staticmethod
    def _is_redirection(token: str) -> bool:
        """``>``, ``>>``, ``<``, ``2>``, ``2>&1``, ``&>`` — оператор, не программа."""
        return bool(re.fullmatch(r"(?:\d*)&?[<>]{1,2}(?:&?\d*)?", token))

    def _clamp_timeout(self, timeout: float | None) -> float:
        if timeout is None:
            return self.default_timeout
        value = float(timeout)
        if value <= 0:
            raise CommandDenied("timeout должен быть положительным числом секунд.")
        return min(value, self.max_timeout)

    def _check_redirections(self, raw: str) -> None:
        for match in re.finditer(r"(?:[0-9]*&?>{1,2})\s*([^\s;&|]+)", raw):
            target = match.group(1).strip("'\"")
            if not target:
                continue
            if target.startswith("/dev/") and target in _ALLOWED_REDIRECT_TARGETS:
                continue
            if any(target.startswith(bad) for bad in _DANGEROUS_PATHS):
                raise CommandDenied(f"Перенаправление в '{target}' запрещено.")
            if target.startswith("/"):
                raise CommandDenied(
                    f"Перенаправление '{target}' ведёт за пределы рабочей директории. "
                    f"Разрешены относительные пути внутри проекта и /dev/null."
                )



# ===========================================================================
# SQL-политика
# ===========================================================================
_ALLOWED_SQL_FIRST: Final = frozenset(
    {"select", "with", "show", "explain", "describe", "desc", "values", "table"}
)
# DML/DDL ловим по синтаксису, а не по «слову где угодно»: иначе запрос
# ``SELECT create FROM audit`` с колонкой ``create`` считался бы записью.
# Мультизапросы и «первый оператор» отсекаются отдельно выше по списку.
_WRITE_SQL_PATTERNS: Final[tuple[tuple[str, str], ...]] = (
    (r"\binsert\s+into\b", "INSERT"),
    (r"\bupdate\s+[\w.]+\s+set\b", "UPDATE"),
    (r"\bdelete\s+from\b", "DELETE"),
    (r"\bmerge\s+into\b", "MERGE"),
    (r"\(\s*(?:insert|update|delete|merge|with)\s", "DML inside CTE"),
    (r"\bdrop\s+(?:table|index|view|schema|database|function|type|sequence|column|role|extension|trigger)\b", "DROP"),
    (r"\balter\s+(?:table|index|view|sequence|type|function|role|database|schema|extension)\b", "ALTER"),
    (
        r"\bcreate\s+(?:or\s+replace\s+)?(?:temp\w*\s+|unlogged\s+)?"
        r"(?:table|index|view|schema|database|function|procedure|trigger|type|sequence|role|extension)\b",
        "CREATE",
    ),
    (r"\btruncate\s+(?:table\s+)?[\w.]+", "TRUNCATE"),
    (r"\brename\s+to\b", "RENAME"),
    (r"\b(grant|revoke)\b", "GRANT/REVOKE"),
    (r"\b(?:vacuum|reindex)\b", "MAINTENANCE"),
    (r"\bcopy\s+(?:[\w.\"']+\s+)?(?:to|from)\b", "COPY (RCE/file access)"),
    (r"\\copy\b", "\\copy (client-side file access)"),
    (r"\block\s+table\b", "LOCK"),
    (r"\bcomment\s+on\b", "COMMENT"),
    (r"\bcall\s+[\w.]+\s*\(", "CALL"),
    (r"\bdo\s+\$?", "DO (anonymous block)"),
    (r"\brefresh\s+materialized\s+view\b", "REFRESH"),
    (r"\b(?:prepare|deallocate)\b", "PREPARE/DEALLOCATE"),
    (r"\b(?:listen|unlisten|notify)\s", "NOTIFY"),
    (r"\bdiscard\b|\breset\b|\bset\s+(?:role|session_authorization|search_path)\b", "SESSION"),
    (r"\binto\s+(?:outfile|dumpfile)\b", "SELECT INTO FILE"),
    (r"\bpg_(?:sleep|advisory_lock|terminate|reload|restart|promote|create_restore_point|read_file|ls_dir)\b", "DANGEROUS PG FUNCTION"),
    (r"\bdblink(?:_exec)?\s*\(", "DBLINK (outbound connection)"),
    (r"\bxmleval|\barray_agg\s*\(\s*$',", "EVAL"),
)
_COMPILED_SQL_WRITE: Final = [
    (re.compile(pattern, re.IGNORECASE), label) for pattern, label in _WRITE_SQL_PATTERNS
]
_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_COMMENT_LINE = re.compile(r"--[^\n]*")
_LIMIT_RE = re.compile(r"\blimit\s+(\d+)", re.IGNORECASE)
_STRING_OR_IDENT = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\$\d|\$\$.*?\$\$", re.DOTALL)


@dataclass(frozen=True)
class SqlPlan:
    """Проверенный запрос + извлечённый LIMIT (для пост-ограничения)."""

    sql: str
    first_keyword: str
    limit: int | None
    statement_count: int


class SqlPolicy:
    """Только чтение + один оператор, без обфускации через комментарии/кавычки."""

    def __init__(self, settings: Settings) -> None:
        self.readonly = settings.sql_readonly
        self.max_rows_default = settings.sql_max_rows_default

    def validate(self, sql: str) -> SqlPlan:
        raw = (sql or "").strip()
        if not raw:
            raise CommandDenied("Пустой SQL-запрос.")
        if len(raw) > 20_000:
            raise CommandDenied("SQL-запрос длиннее 20000 символов — разбейте его.")

        # Убираем строки/идентификаторы из анализа, чтобы 'delete from x' внутри
        # строкового литерала не считался оператором, а реальные операторы — нет.
        skeleton = _STRING_OR_IDENT.sub(" ", raw)
        skeleton = _COMMENT_BLOCK.sub(" ", skeleton)
        skeleton = _COMMENT_LINE.sub(" ", skeleton)
        skeleton = skeleton.strip().rstrip(";").strip()
        if not skeleton:
            raise CommandDenied("В запросе нет исполняемого оператора (только комментарии).")

        statements = [part for part in skeleton.split(";") if part.strip()]
        if len(statements) > 1:
            raise CommandDenied(
                f"Обнаружено {len(statements)} оператора; мультизапросы запрещены."
            )

        first = statements[0].strip().split(None, 1)[0].lower()
        if first not in _ALLOWED_SQL_FIRST:
            raise CommandDenied(
                f"Первый оператор '{first.upper()}' не разрешён. "
                f"Допустимы: {', '.join(sorted(op.upper() for op in _ALLOWED_SQL_FIRST))}."
            )
        if self.readonly:
            for pattern, label in _COMPILED_SQL_WRITE:
                if pattern.search(skeleton):
                    raise CommandDenied(
                        f"Режим только-для-чтения: в запросе обнаружен оператор {label}. "
                        f"Изменения вносите через миграции Alembic (exec_command)."
                    )

        match = _LIMIT_RE.search(skeleton)
        return SqlPlan(
            sql=raw.rstrip().rstrip(";"),
            first_keyword=first,
            limit=int(match.group(1)) if match else None,
            statement_count=len(statements),
        )


# ===========================================================================
# Маскировка секретов
# ===========================================================================
_SECRET_RULES: Final[tuple[tuple[str, str], ...]] = (
    (
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        "[REDACTED:private-key]",
    ),
    (
        r"(?i)([\"']?(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|"
        r"secret[_-]?key|auth[_-]?token|token|authorization|dsn|connection[_-]?(?:string|uri)|"
        r"db[_-]?url|redis[_-]?url|postgres(?:ql)?(?:_dsn)?)[\"']?\s*[:=]\s*)"
        r"(?:'[^']*'|\"[^\"]*\"|[^\s,;&'\"]+)",
        r"\1[REDACTED]",
    ),
    (r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}", r"\1 [REDACTED]"),
    (r"\b(?:sk|pk|rk|ghp|gho|ghu|ghs|glpat|xox[abprs]-[A-Za-z0-9-]{6,})-[A-Za-z0-9_\-]{8,}\b", "[REDACTED:token]"),
    (r"AKIA[0-9A-Z]{16}", "[REDACTED:aws-key]"),
    # scheme://user:password@host  ->  scheme://user:[REDACTED]@host
    (r"(?i)\b([a-z][a-z0-9+.\-]*://)([^\s/@:]+)(:[^\s/@]+)?@", r"\1\2:[REDACTED]@"),
)
_COMPILED = [(re.compile(pattern), repl) for pattern, repl in _SECRET_RULES]


def redact_secrets(text: str | None) -> str:
    """Вырезает секреты из *всех* выводимых строк (логи, env, дампы БД).

    Единственный конвейер: каждый адаптер вызывает его перед отдачей данных
    модели, поэтому ключи не попадают в контекст LLM и в чат-канал.
    """
    if not text:
        return text or ""
    result = text
    for pattern, repl in _COMPILED:
        result = pattern.sub(repl, result)
    return result


def mask_setting_name(name: str) -> str:
    """True, если имя переменной окружения похоже на секрет (для value_preview)."""
    lowered = name.lower()
    markers = ("password", "secret", "token", "key", "credential", "dsn", "uri", "url", "auth")
    return any(marker in lowered for marker in markers)


def format_timestamp(mtime: float | None) -> str:
    if mtime is None:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
