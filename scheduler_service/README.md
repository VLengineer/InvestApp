# scheduler_service

Легковесный микросервис (FastAPI) циклического опроса n8n: очередь задач в
PostgreSQL + паттерн Callback. Состоит из HTTP API и фонового воркера, который
запускается вместе с приложением (lifespan → asyncio.create_task).

## Цикл воркера
1. `scheduler_state.is_active == false` → пауза 5 с, повтор проверки.
2. Иначе: создаёт `tasks(id=uuid, status='pending')`, шлёт POST
   `N8N_WEBHOOK_URL` c `{"task_id": uuid}` и `Authorization: Bearer <N8N_WEBHOOK_JWT_TOKEN>`.
3. Каждые 10 с читает статус задачи из БД (ожидание callback от n8n):
   - `completed` → пауза 10 минут;
   - `rejected`  → пауза 5 минут.
4. Ошибки не роняют цикл; «вечный» pending страхуется `TASK_WAIT_TIMEOUT_S`.

## Эндпоинты
| Метод | Путь | Защита |
|---|---|---|
| POST | `/api/v1/scheduler/start` | JWT Bearer (единый секрет проекта) |
| POST | `/api/v1/scheduler/stop`  | JWT Bearer |
| GET  | `/api/v1/scheduler/state`  | JWT Bearer |
| GET  | `/api/v1/scheduler/tasks/{uuid}` | JWT Bearer |
| POST | `/api/v1/scheduler/callback` | заголовок `X-Callback-Secret` = `CALLBACK_SECRET` |
| GET  | `/live`, `/ready` | без авторизации |

Swagger: http://localhost:8200/docs (токен — `python get_token.py --secret "$JWT_SECRET_KEY"`).

## Схема БД
Таблицы `scheduler_state` (singleton: id=1, is_active) и `tasks`
(uuid PK, status pending/completed/rejected, created_at, updated_at) создаются
`init_db/04_init_scheduler.sql` при первом старте postgres и идемпотентно самим
сервисом (`ensure_schema`) для локального запуска.

## Запуск
```bash
cp .env.example .env   # заполнить секреты (см. python_test/.env)
docker compose up -d --build scheduler_service
# или локально:
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8200
```

## Пример callback из n8n (HTTP Request node)
```
POST http://scheduler_service:8200/api/v1/scheduler/callback
Headers: X-Callback-Secret: <CALLBACK_SECRET>, Content-Type: application/json
Body:    {"task_id": "<uuid из тела вебхука>", "status": "completed"}   # или "rejected"
```
