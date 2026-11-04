"""Настройки сервера — единственное место, где читается окружение.

Разделяй ответственности: модули знают только типизированные значения из этого
объекта, переменные окружения не «проттекают» в бизнес-логику (Composition Root
инжектирует Settings в адаптеры).

Значения по умолчанию взяты из фактического docker-compose проекта:
WORKSPACE_DIR=/workspace, пострижный контейнер называется ``postgres``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name, default)
    return value if value.strip() else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


def _env_csv(name: str, default: str) -> tuple[str, ...]:
    raw = os.environ.get(name, "") or default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.environ.get(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "y", "t"}


@dataclass(frozen=True)
class Limits:
    """Потолки объёма вывода — защита контекста LLM от взрыва токенов."""

    read_bytes: int = 262_144          # ~256 KiB за одно чтение файла
    read_max_lines: int = 4_000
    write_max_bytes: int = 1_048_576   # 1 MiB за запись
    exec_output_bytes: int = 100_000   # суммарно stdout+stderr у exec/run_local
    exec_stream_sample_bytes: int = 8_192  # порция живого вывода при timeout
    tail_max_lines: int = 500
    tail_max_bytes: int = 200_000
    search_max_matches: int = 400
    search_max_files: int = 5_000
    glob_max_files: int = 5_000
    tree_max_entries: int = 800
    tree_max_depth: int = 5
    list_services_max: int = 100
    sql_max_rows: int = 200
    table_max_rows: int = 100
    diff_max_hunks: int = 40
    http_max_bytes: int = 262_144


@dataclass(frozen=True)
class Settings:
    """Все конфигурационные входы приложения."""

    workspace_dir: Path
    protected_dirs: tuple[str, ...]
    limits: Limits = field(default_factory=Limits)

    # --- таймауты -------------------------------------------------------
    exec_default_timeout: float = 120.0
    exec_max_timeout: float = 900.0
    stream_poll_interval: float = 0.2
    local_default_timeout: float = 60.0
    local_max_timeout: float = 300.0
    docker_api_timeout: float = 10.0
    http_timeout_default: float = 15.0
    http_timeout_max: float = 60.0

    # --- политики -------------------------------------------------------
    shell_allow: frozenset[str] = frozenset(
        {
            "git", "python", "python3", "pip", "pip3", "pytest", "alembic", "poetry",
            "npm", "npx", "node", "yarn", "pnpm", "tsc", "vue-tsc", "vite", "eslint",
            "prettier", "deno", "go", "make", "cmake", "cargo", "uv", "uvicorn", "gunicorn",
            "celery", "mypy", "ruff", "black", "isort", "flake8", "bandit",
            "ls", "cat", "head", "tail", "wc", "sort", "uniq", "grep", "egrep", "fgrep",
            "rg", "ag", "find", "tree", "du", "df", "stat", "file", "basename", "dirname",
            "realpath", "readlink", "touch", "mkdir", "cp", "mv", "sed", "awk", "jq",
            "diff", "cmp", "tr", "cut", "paste", "xargs", "tee", "env", "echo", "printf",
            "which", "whereis", "type", "date", "id", "uname", "uptime", "ps", "top",
            "md5sum", "sha256sum", "base64", "tar", "gzip", "gunzip", "zip", "unzip",
            "curl", "wget", "sleep", "seq", "yes", "timeout", "openapi", "psql", "pg_dump",
        }
    )
    shell_extra_allowed: tuple[str, ...] = ()
    shell_deny: frozenset[str] = frozenset(
        {"sudo", "su", "rm", "mkfs", "dd", "shutdown", "reboot", "halt", "init", "systemctl",
         "shutdown", "chown", "chmod", "mount", "umount", "nsenter", "unshare", "crontab",
         "visudo", "useradd", "userdel", "usermod", "groupadd", "passwd", "chroot",
         "setenforce", "iptables", "ip6tables", "nft", "ufw", "dmesg", "free",
         "bpftrace", "perf", "strace", "ltrace", "gdb", "lldb", "ebuild", "pipeload"}
    )
    sql_readonly: bool = True
    sql_max_rows_default: int = 200
    http_allowlist: tuple[str, ...] = ()

    # --- инфраструктура -------------------------------------------------
    # Фолбэк, если в контейнере нет подписей compose (standalone-запуск демона).
    service_fallback: dict[str, str] = field(
        default_factory=lambda: {
            "backend-frontend": "backend-frontend",
            "python_test": "python_test",
            "scheduler_service": "scheduler_service",
            "frontend": "frontend",
            "postgres": "postgres",
        }
    )
    postgres_service: str = "postgres"
    postgres_db_env: str = "POSTGRES_DB"
    postgres_user_env: str = "POSTGRES_USER"

    # --- транспорт ------------------------------------------------------
    sse_path: str = "/sse"
    message_path: str = "/messages/"
    allow_hosts: tuple[str, ...] = ()


def load_settings() -> Settings:
    """Собирает настройки из окружения (12-factor)."""
    workspace = Path(_env_str("WORKSPACE_DIR", "/workspace")).expanduser()
    return Settings(
        workspace_dir=workspace,
        protected_dirs=_env_csv("MCP_PROTECTED_DIRS", ".git,.env,.venv,node_modules,__pycache__"),
        limits=Limits(
            read_bytes=_env_int("MCP_READ_MAX_BYTES", 262_144),
            write_max_bytes=_env_int("MCP_WRITE_MAX_BYTES", 1_048_576),
            exec_output_bytes=_env_int("MCP_EXEC_MAX_OUTPUT", 100_000),
            tail_max_lines=_env_int("MCP_TAIL_MAX_LINES", 500),
            search_max_matches=_env_int("MCP_SEARCH_MAX_MATCHES", 400),
            tree_max_entries=_env_int("MCP_TREE_MAX_ENTRIES", 800),
            http_max_bytes=_env_int("MCP_HTTP_MAX_BYTES", 262_144),
        ),
        exec_default_timeout=_env_float("MCP_EXEC_TIMEOUT", 120.0),
        exec_max_timeout=_env_float("MCP_EXEC_MAX_TIMEOUT", 900.0),
        local_default_timeout=_env_float("MCP_LOCAL_TIMEOUT", 60.0),
        local_max_timeout=_env_float("MCP_LOCAL_MAX_TIMEOUT", 300.0),
        docker_api_timeout=_env_float("MCP_DOCKER_API_TIMEOUT", 10.0),
        http_timeout_default=_env_float("MCP_HTTP_TIMEOUT", 15.0),
        http_timeout_max=_env_float("MCP_HTTP_MAX_TIMEOUT", 60.0),
        shell_extra_allowed=_env_csv("MCP_SHELL_ALLOW", ""),
        sql_readonly=_env_bool("MCP_SQL_READONLY", True),
        sql_max_rows_default=_env_int("MCP_SQL_MAX_ROWS", 200),
        http_allowlist=_env_csv("MCP_HTTP_ALLOWLIST", ""),
        postgres_service=_env_str("MCP_POSTGRES_SERVICE", "postgres"),
        sse_path=_env_str("MCP_SSE_PATH", "/sse"),
        message_path=_env_str("MCP_MESSAGE_PATH", "/messages/"),
        allow_hosts=_env_csv("MCP_ALLOWED_HOSTS", ""),
    )
