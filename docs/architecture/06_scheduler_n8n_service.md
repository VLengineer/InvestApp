# Сервис 6. Планировщик интеграции с n8n (очередь задач + callback)

**Реализация:** отдельный микросервис `scheduler_service` (FastAPI, порт 8200) + фоновый воркер
**Ключевые модули:**
- `scheduler_service/app/api/routes/scheduler.py` — start/stop/state/callback/tasks
- `scheduler_service/app/workers/scheduler_worker.py` — бесконечный цикл опроса
- `scheduler_service/app/db/repository.py` — SQL `scheduler_state`, `tasks`
- `scheduler_service/app/core/config.py` — env-настройки (порт 8200, интервалы, секреты)
- `init_db/04_init_scheduler.sql` / `scheduler_service/app/db/database.py` — DDL
- тесты: `test_scheduler_api.py`, `test_scheduler_worker.py`, `test_callback_secret.py`, `test_config.py`, `test_repository.py`, `test_health.py`

## Назначение

Управление периодическим запуском процесса в n8n («проверить новости»): воркер создаёт задачу с UUID в PostgreSQL, дёргает POST-вебхук n8n и **ожидает асинхронный callback** (`completed`/`rejected`) через polling статуса в БД; по результату делает паузу (10 мин после completed, 5 мин после rejected). Флагом `is_active` можно управлять извне (REST), не перезапуская контейнер.

## API контракты

### POST `/api/v1/scheduler/start` | `/stop` (JWT Bearer)
Ответ `SchedulerStateResponse`: `{is_active: bool, message: str}` («Планировщик запущен/остановлен»). Пишет singleton-строку `scheduler_state(id=1)` upsert'ом.

### GET `/api/v1/scheduler/state` (JWT)
`{is_active, message:"ok"}`; если строки нет (голая БД) — считается активной.

### POST `/api/v1/scheduler/callback` (без JWT; заголовок `X-Callback-Secret`)
Вход `CallbackRequest`: `{task_id: UUID, status: "completed"|"rejected"}`.
Ответ `CallbackResponse`: `{task_id, status, updated_at}`; `404` если task_id неизвестен (даёт сигнал n8n), `401` при неверном/отсутствующем секрете (сравнение `hmac.compare_digest` — против timing-атак; сообщение единое, без раскрытия значения).

### GET `/api/v1/scheduler/tasks/{task_id}` (JWT) — отладка цепочки
`{"task_id": str, "status": str}`; 404 если нет; не-UUID → 422.

### Health (без авторизации)
`GET /live` (статика + `worker_alive`), `GET /ready` (проверка SELECT 1 в БД + живой воркер; иначе `degraded`).

## Модель данных

```sql
scheduler_state(id INT PK CHECK(id=1), is_active BOOL DEFAULT TRUE)   -- singleton
tasks(id uuid PK, status VARCHAR(16) CHECK IN ('pending','completed','rejected'),
      created_at, updated_at)  -- + индексы status, created_at DESC
```
DDL идемпотентна; прод — docker-entrypoint-initdb.d, локаль — `SCHEMA_DDL` того же текста в `app/db/database.py`.

## Бизнес-правила (цикл воркера)

1. Пока `is_active=false` — сон `inactive_check_interval_s` (5 c) и повтор (короткий цикл, stop действует почти мгновенно).
2. Новая задача: UUID генерируется **воркером** (ключ идемпотентности callback), INSERT `status='pending'`, затем POST на `N8N_WEBHOOK_URL` (`http://n8n:5678/webhook/start_process`) телом `{"task_id": ...}` с `Authorization: Bearer N8N_WEBHOOK_JWT_TOKEN` (если непустой).
3. Успех запуска = HTTP 2xx **и** не `{"status": false}` в теле (штатный ответ n8n-workflow — `{"status": true, "description":"launched"}`).
4. Если n8n не принял запуск — задача остаётся `pending` в БД, но цикл не зависает: пауза как после rejected (300 с).
5. Ожидание: polling `get_task_status` каждые `poll_interval_s` (10 с); `completed|rejected` → выход; строка исчезла → трамбуется как мягкий reject (пауза 5 мин).
6. Страховочный таймаут `task_wait_timeout_s` (3600 с): задача помечается `rejected` и цикл освобождается — «вечный pending» невозможен.
7. Паузы: completed → `sleep_after_completed_s` (600 с), rejected → `sleep_after_rejected_s` (300 с).
8. Санация при старте: все `pending` старше таймаута помечаются `rejected` (`mark_stale_pending_rejected`) — страховка после падения контейнера.
9. Любая ошибка цикла → лог ERROR + сон 30 с + продолжение (цикл никогда не умирает, кроме штатной отмены `CancelledError`).
10. Состояние живёт в БД, не в памяти: переживает рестарты, HTTP-часть масштабируется горизонтально. Никаких блокирующих вызовов (только asyncio/asyncpg/httpx).

## Обработка ошибок

| Ситуация | Реакция |
|---|---|
| Callback на неизвестный task_id | 404 (n8n видит, что задача уже ссанитизирована) |
| Неверный X-Callback-Secret | 401 |
| БД недоступна в момент create_task/HTTP-ошибки n8n | exception → общий обработчик цикла: лог + 30 с + retry следующего цикла |
| Нет JWT-токена для вебхука | запрос уходит без Authorization (зависит от настроек вебхука n8n) |
| Старт упал на санации | WARNING/ERROR, старт продолжается (не критично) |

## Безопасность

Два канала: человек/Swagger — единый JWT проекта (тот же `JWT_SECRET_KEY`, что у python_test; `app/core/security.py`); машина n8n → сервис — статический секрет `CALLBACK_SECRET` (≥16 симв., compare_digest). Секреты только из env, маскируются в логах. Значения по умолчанию заглушек в `.env.example` заменены на уникальные ≥32 симв.

## Паттерны

Callback/Async-request-response c persistent state (таблица tasks), Polling-waiter, Singleton-state row, Circuit «graceful degradation» (паузы вместо падений), Repository (SQL-константы модуля), Background worker в lifespan FastAPI (start/cancel симметрично).

## Тесты

Полный набор unit-тестов (`scheduler_service/app/tests/`): API start/stop/state, secret-валидация, репозиторий (мок пула), worker-циклы (мок БД/HTTP), health, конфигурация.
