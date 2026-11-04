"""
MCP-сервер для агента-кодера.

Три группы инструментов:
  1. Файловые (read/write/edit/list/delete/search) — работают напрямую в
     примонтированном /workspace (монтируется в docker-compose.yml).
  2. exec_command — выполняет shell-команды внутри целевого контейнера сервиса
     через docker.sock, рабочая директория — /app внутри контейнера.
  3. run_local_command / list_services — команды в самом контейнере MCP
     (git и т.п.) и список запущенных контейнеров.

Безопасность:
  - safe_path() защищает от path traversal за пределы WORKSPACE;
  - BLACKLIST блокирует опасные команды (rm -rf /, docker/systemctl и т.п.);
  - .git, node_modules, __pycache__ защищены от записи/удаления файлами.
"""

import fnmatch
import os
import shlex
import subprocess

import docker
from mcp.server.fastmcp import FastMCP

# host/port передаём через конструктор (settings): в разных версиях библиотеки
# mcp сигнатура mcp.run() отличается (run(transport=...) без host/port),
# а FastMCP(name, host=..., port=...) поддерживается всеми версиями 1.x.
MCP_HOST = "0.0.0.0"
MCP_PORT = int(os.environ.get("PORT", "9000"))

mcp = FastMCP("Project Coder MCP Server", host=MCP_HOST, port=MCP_PORT)

# Директория проекта, примонтированная в контейнер mcp-server (см. docker-compose.yml)
WORKSPACE = os.environ.get("MCP_WORKSPACE", "/workspace")

# Контейнер Docker изнутри недоступен по имени хоста — берём адрес из env
# (compose передаёт DOCKER_HOST), при локальном запуске — стандартный socket.
DOCKER_HOST = os.environ.get("DOCKER_HOST") or "unix:///var/run/docker.sock"

_docker_client = None
_docker_error = None


def get_docker():
    """Ленивый доступ к Docker: отсутствие docker.sock не должно валить сервер,
    файловые инструменты и run_local_command работают и без Docker."""
    global _docker_client, _docker_error
    if _docker_client is not None:
        return _docker_client
    if _docker_error is not None:
        raise RuntimeError(
            f"Docker недоступен ({_docker_error}). Инструменты exec_command/"
            "list_services требуют смонтированный /var/run/docker.sock."
        )
    try:
        _docker_client = docker.DockerClient(base_url=DOCKER_HOST)
    except Exception as e:  # DockerException и прочее
        _docker_error = str(e)
        raise RuntimeError(_docker_error)
    return _docker_client

# Сервисы проекта: имя сервиса в compose -> имя контейнера и workdir внутри него
SERVICES = {
    "backend-frontend": {"container": "backend-frontend", "workdir": "/app"},
    "python_test": {"container": "python_test", "workdir": "/app"},
    "scheduler_service": {"container": "scheduler_service", "workdir": "/app"},
    "frontend": {"container": "frontend", "workdir": "/app"},
}

# Пути, которые агенту-кодеру трогать нельзя
PROTECTED_DIRS = (".git", "node_modules", "__pycache__", ".venv", "venv")

# Стоп-лист для команд (подстроки; отсекает опасные операции)
COMMAND_BLACKLIST = (
    "rm -rf /", "mkfs", "dd if=", ":(){", "shutdown", "reboot", "halt",
    "docker", "systemctl", "chown -r /", "chmod -r 777 /",
)

MAX_OUTPUT = 100_000  # максимум символов вывода на срез


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def safe_path(path: str) -> str:
    """Разрешает путь относительно WORKSPACE с защитой от Path Traversal."""
    path = (path or "").strip().lstrip("/\\")
    full_path = os.path.realpath(os.path.join(WORKSPACE, path))
    ws = os.path.realpath(WORKSPACE)
    if full_path != ws and not full_path.startswith(ws + os.sep):
        raise ValueError(f"Access denied: path '{path}' escapes the workspace.")
    rel = os.path.relpath(full_path, ws)
    top = rel.split(os.sep)[0]
    if top in PROTECTED_DIRS:
        raise ValueError(f"Access denied: '{top}' is a protected directory.")
    return full_path


def check_command(command: str):
    """Возвращает сообщение об ошибке, если команда запрещена."""
    low = command.lower()
    for bad in COMMAND_BLACKLIST:
        if bad in low:
            return f"Blocked: command contains forbidden token '{bad.strip()}'."
    return None


def get_container(service_name: str):
    """Поиск работающего контейнера: сначала по точному имени сервиса,
    затем по подстроке имени."""
    if service_name in SERVICES:
        name = SERVICES[service_name]["container"]
        try:
            c = get_docker().containers.get(name)
            if c.status == "running":
                return c
        except docker.errors.NotFound:
            pass
    for c in get_docker().containers.list():
        if service_name in c.name:
            return c
    return None


def truncate(text: str) -> str:
    if len(text) > MAX_OUTPUT:
        return text[:MAX_OUTPUT] + "\n... [output truncated]"
    return text


# ---------------------------------------------------------------------------
# Инструменты работы с файлами
# ---------------------------------------------------------------------------

@mcp.tool()
def read_file(path: str, start_line: int = 0, end_line: int = 0) -> str:
    """Читает файл проекта (путь относительно корня проекта).

    Опционально диапазон строк (1-based, включительно): start_line=10,
    end_line=40. 0 — читать весь файл.
    """
    p = safe_path(path)
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    header = ""
    if start_line or end_line:
        s = max(start_line, 1)
        e = end_line if end_line else len(lines)
        picked = lines[s - 1 : e]
        header = f"[{path}: lines {s}-{min(e, s + len(picked) - 1)} of {len(lines)}]\n"
        lines = picked
    return truncate(header + "".join(lines))


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Создаёт или полностью перезаписывает файл в проекте (UTF-8)."""
    p = safe_path(path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return f"File '{path}' written ({len(content)} chars)."


@mcp.tool()
def edit_file(path: str, old_str: str, new_str: str, replace_all: bool = False) -> str:
    """Точечная замена в файле: находит old_str и заменяет на new_str.

    Ошибка, если old_str не найден или найден более одного раза
    (при replace_all=False). Используйте для правок без полной перезаписи.
    """
    p = safe_path(path)
    with open(p, "r", encoding="utf-8") as f:
        text = f.read()
    count = text.count(old_str)
    if count == 0:
        return f"ERROR: old_str not found in '{path}'. Nothing changed."
    if count > 1 and not replace_all:
        return (
            f"ERROR: old_str found {count} times in '{path}'. "
            "Add more context to old_str or set replace_all=true. Nothing changed."
        )
    with open(p, "w", encoding="utf-8") as f:
        f.write(text.replace(old_str, new_str))
    return f"Edited '{path}': {count} replacement(s) applied."


@mcp.tool()
def list_directory(path: str = "", depth: int = 1) -> str:
    """Дерево файлов/папок директории проекта (пустой путь = корень).

    Служебные папки (.git, node_modules, __pycache__) пропускаются.
    depth — уровень вложенности (1-5).
    """
    root = safe_path(path) if path.strip() else os.path.realpath(WORKSPACE)
    depth = max(1, min(depth, 5))
    out = []

    def walk(d: str, level: int):
        try:
            entries = sorted(os.scandir(d), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return
        for e in entries:
            if e.name in PROTECTED_DIRS or e.name == ".env":
                continue
            out.append("  " * level + e.name + ("/" if e.is_dir() else ""))
            if e.is_dir() and level < depth:
                walk(e.path, level + 1)

    walk(root, 0)
    return truncate("\n".join(out) or "(empty)")


@mcp.tool()
def delete_path(path: str) -> str:
    """Удаляет файл или ПУСТУЮ директорию в проекте (защита от случайной рекурсии)."""
    p = safe_path(path)
    if os.path.isdir(p):
        os.rmdir(p)
    else:
        os.remove(p)
    return f"Deleted '{path}'."


@mcp.tool()
def search_in_files(pattern: str, path: str = "", glob: str = "*") -> str:
    """Ищет подстроку pattern в файлах проекта рекурсивно.

    path — поддиректория поиска (пусто = корень); glob — фильтр имён,
    например '*.py' или '*.vue'. Результат: путь:номер:строка.
    """
    root = safe_path(path) if path.strip() else os.path.realpath(WORKSPACE)
    matches = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in PROTECTED_DIRS]
        for fn in filenames:
            if not fnmatch.fnmatch(fn, glob):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        if pattern in line:
                            rel = os.path.relpath(fp, WORKSPACE)
                            matches.append(f"{rel}:{i}: {line.rstrip()[:200]}")
                            if len(matches) >= 200:
                                return truncate(
                                    "\n".join(matches) + "\n... [too many matches]"
                                )
            except (UnicodeDecodeError, OSError):
                continue
    return "\n".join(matches) if matches else f"No matches for '{pattern}'."


# ---------------------------------------------------------------------------
# Инструменты выполнения команд
# ---------------------------------------------------------------------------

@mcp.tool()
def list_services() -> str:
    """Список известных сервисов и запущенных контейнеров (для выбора service
    в exec_command)."""
    known = "\n".join(
        f"  {name} -> container '{info['container']}', workdir {info['workdir']}"
        for name, info in SERVICES.items()
    )
    rows = []
    try:
        for c in get_docker().containers.list():
            img = c.image.tags[0] if c.image.tags else c.image.short_id
            rows.append(f"  {c.name}\t{c.status}\t{img}")
    except Exception as e:
        return f"Docker недоступен: {e}"
    return (
        "Known services (for exec_command):\n" + known
        + "\n\nRunning containers:\n" + ("\n".join(rows) or "  (none)")
    )


@mcp.tool()
def exec_command(service: str, command: str) -> str:
    """Выполняет shell-команду внутри контейнера указанного сервиса проекта.

    service: backend-frontend | python_test | scheduler_service | frontend
    (или любое другое имя запущенного контейнера).
    Команда выполняется в рабочей директории кода внутри контейнера (/app).
    Примеры:
      pytest tests/ -q                     — тесты Python-сервисов
      alembic revision --autogenerate -m x — миграции
      npm run build                        — сборка фронтенда
      pip install -r requirements.txt      — установка зависимостей
    Формат ответа: [контейнер:workdir] exit=<код>\n<stdout+stderr>.
    """
    err = check_command(command)
    if err:
        return err

    try:
        container = get_container(service)
    except Exception as e:
        return f"Docker недоступен: {e}"
    if not container:
        return (
            f"ERROR: running container for service '{service}' not found. "
            "Call list_services() to see what is up."
        )

    workdir = SERVICES.get(service, {}).get("workdir", "/app")
    try:
        proc = container.exec_run(["sh", "-c", command], workdir=workdir, demux=False)
    except Exception as e:
        return f"ERROR while executing in '{container.name}': {e}"

    output = proc.output.decode("utf-8", errors="replace") if proc.output else ""
    return f"[{container.name}:{workdir}] exit={proc.exit_code}\n{truncate(output)}"


@mcp.tool()
def run_local_command(command: str, timeout: int = 60) -> str:
    """Выполняет команду напрямую в контейнере mcp-server (git, python, grep).

    Рабочая директория — корень проекта /workspace. Подходит для git-операций
    (status/diff/log/add/commit) и быстрых проверок без входа в сервисы.
    """
    err = check_command(command)
    if err:
        return err
    args = shlex.split(command)
    if not args:
        return "ERROR: empty command."
    try:
        res = subprocess.run(
            args, cwd=WORKSPACE, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {timeout}s."
    except FileNotFoundError:
        return f"ERROR: executable '{args[0]}' not found in mcp-server image."
    out = (res.stdout or "") + (("\n[stderr]\n" + res.stderr) if res.stderr else "")
    return f"exit={res.returncode}\n{truncate(out)}"


if __name__ == "__main__":
    # host/port уже заданы в конструкторе FastMCP (settings) — см. начало файла.
    mcp.run(transport="sse")
