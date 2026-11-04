"""Пакет реализации MCP-сервера для агента-кодера.

Слои (Clean Architecture, адаптеры на границах):

    config.py      настройки из окружения (composition root читает их одним местом)
    security.py    политики: пути, shell-команды, SQL, секреты  (core, без I/O)
    formatting.py  представление выводов: обрезка, diff, таблицы (core, без I/O)
    models.py      контракты результатов инструментов (pydantic)
    docker_api.py  доступ к Docker-демонам: exec/логи/psql/списки (gateway)
    tools_*.py     слой инструментов FastMCP (adapters)
    resources.py   MCP-ресурсы проекта (дёшево по токенам, см. README)
    prompts.py     готовые рабочие сценарии
    server.py      composition root: собирает FastMCP из блоков выше
"""

__all__ = ["config", "docker_api", "formatting", "models", "security"]
