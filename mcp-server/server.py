from mcp.server.fastmcp import FastMCP
import os
import docker

mcp = FastMCP("Project MCP Server")
client = docker.from_env()

# Директория, куда будет примонтирован проект
WORKSPACE = "/workspace" 

def safe_path(path: str) -> str:
    """Защита от Path Traversal"""
    path = path.lstrip("/\\")
    full_path = os.path.abspath(os.path.join(WORKSPACE, path))
    if not full_path.startswith(os.path.abspath(WORKSPACE)):
        raise ValueError("Access denied: Path traversal detected.")
    return full_path

def get_container(service_name: str):
    """Поиск контейнера по части имени (сервису в docker-compose)"""
    for c in client.containers.list():
        if service_name in c.name:
            return c
    return None

# --- ИНСТРУМЕНТЫ РАБОТЫ С ФАЙЛАМИ ---

@mcp.tool()
def read_file(path: str) -> str:
    """Читает содержимое файла проекта"""
    with open(safe_path(path), "r", encoding="utf-8") as f:
        return f.read()

@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Создает или перезаписывает файл в проекте"""
    full_path = safe_path(path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"File {path} successfully written."

@mcp.tool()
def list_directory(path: str = "") -> str:
    """Возвращает список файлов и папок в директории проекта"""
    full_path = safe_path(path)
    items = os.listdir(full_path)
    return "\n".join(items)

# --- ИНСТРУМЕНТЫ ВЫПОЛНЕНИЯ КОМАНД ---

@mcp.tool()
def run_backend_frontend_command(command: str) -> str:
    """Выполняет команды (pytest, python, alembic) внутри контейнера backend"""
    allowed = ("pytest", "python", "alembic", "pip")
    if not command.startswith(allowed):
        return f"Blocked. Allowed prefixes: {allowed}"
        
    container = get_container("backend-frontend") # Подставь имя своего сервиса из compose
    if not container:
        return "Backend container not found."
        
    # Выполняем команду внутри контейнера
    exec_result = container.exec_run(f"bash -c '{command}'", workdir="/app")
    return exec_result.output.decode('utf-8', errors='replace')

@mcp.tool()
def run_backend_command(command: str) -> str:
    """Выполняет команды (pytest, python, alembic) внутри контейнера backend"""
    allowed = ("pytest", "python", "alembic", "pip")
    if not command.startswith(allowed):
        return f"Blocked. Allowed prefixes: {allowed}"
        
    container = get_container("python_test") # Подставь имя своего сервиса из compose
    if not container:
        return "Backend container not found."
        
    # Выполняем команду внутри контейнера
    exec_result = container.exec_run(f"bash -c '{command}'", workdir="/app")
    return exec_result.output.decode('utf-8', errors='replace')

@mcp.tool()
def run_scheduler_service_command(command: str) -> str:
    """Выполняет команды (pytest, python, alembic) внутри контейнера backend"""
    allowed = ("pytest", "python", "alembic", "pip")
    if not command.startswith(allowed):
        return f"Blocked. Allowed prefixes: {allowed}"
        
    container = get_container("scheduler_service") # Подставь имя своего сервиса из compose
    if not container:
        return "Backend container not found."
        
    # Выполняем команду внутри контейнера
    exec_result = container.exec_run(f"bash -c '{command}'", workdir="/app")
    return exec_result.output.decode('utf-8', errors='replace')

@mcp.tool()
def run_frontend_command(command: str) -> str:
    """Выполняет команды (npm, node, vue-cli) внутри контейнера frontend"""
    allowed = ("npm", "node", "vue", "npx")
    if not command.startswith(allowed):
        return f"Blocked. Allowed prefixes: {allowed}"
        
    container = get_container("frontend") # Подставь имя своего сервиса из compose
    if not container:
        return "Frontend container not found."
        
    exec_result = container.exec_run(f"sh -c '{command}'", workdir="/app")
    return exec_result.output.decode('utf-8', errors='replace')

if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=9000)