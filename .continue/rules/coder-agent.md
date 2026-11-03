description: Правила для агента-кодера (работа через MCP-инструменты проекта)
---

Ты работаешь с проектом через MCP-сервер `project-coder`. Соблюдай правила:

1. Все пути файлов — относительные от корня проекта (например `backend-frontend/app/main.py`).
   Не выходи за пределы проекта; папки `.git`, `node_modules`, `__pycache__` трогать нельзя.
2. Для правок предпочитай `edit_file` (точная замена) вместо полной перезаписи `write_file`.
3. Перед запуском тестов/сборки определяй нужный сервис:
   - `backend-frontend` — BFF дашборда (FastAPI, pytest, alembic)
   - `python_test` — RAG-сервис (FastAPI + pgvector/Ollama)
   - `scheduler_service` — планировщик задач
   - `frontend` — Vue/Vite (npm run build, npm test)
4. Команды запускай через `exec_command(service, command)` — они выполняются внутри
   контейнера сервиса в `/app`; git и простые проверки — через `run_local_command`.
5. Если контейнер сервиса не найден — сначала вызови `list_services()` и сообщи пользователю,
   что нужно поднять стек: `docker compose up -d`.
6. После изменений Python-кода прогоняй соответствующие тесты (`pytest -q`) через `exec_command`
   и не завершай задачу с падающими тестами без объяснения причины.
