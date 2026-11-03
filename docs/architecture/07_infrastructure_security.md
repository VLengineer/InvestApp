# Сервис 7. Инфраструктурный слой: безопасность, DI, конфигурация, логирование

**Реализация:** сквозной код обоих микросервисов
**Ключевые модули:**
- `python_test/app/core/security.py` (+ зеркало в `scheduler_service/app/core/security.py`) — JWT/RBAC
- `tools/get_token.py`, `secret.py`, `python_test/secret.py` — генерация токенов и секретов
- `python_test/app/core/config.py`, `scheduler_service/app/core/config.py` — pydantic-settings
- `python_test/app/core/container.py` — Composition Root (DI)
- `python_test/app/main.py` — FastAPI app, lifespan, security-заголовки, обработчик ошибок
- `python_test/app/core/logging.py` — маскирование секретов
- `python_test/app/core/exceptions.py` — иерархия доменных ошибок
- `.env.example` (оба сервиса), `docker-compose.yml`, `Makefile`

## Назначение

Единая «швейцарская» прослойка, которую потребляют все логические сервисы (01–06): аутентификация одним токеном, конфигурация из окружения, сборка графа зависимостей, единый формат ошибок, безопасное логирование, health-эндпоинты.

## Контракт доступа (не HTTP-эндпоинт, а сквозное правило)

**Схема:** один JWT HS256 на весь проект (admin-ключи и X-API-Key упразднены). Заголовок `Authorization: Bearer <token>`; в Swagger UI — кнопка Authorize (`HTTPBearer`, `auto_error=False` — сообщения формируются единообразно).

| Параметр | Значение |
|---|---|
| Алгоритм | строгий whitelist `["HS256"]` (исключает `alg=none`/подмену) |
| Обязательные claims | `iat`, `sub` (+`exp` только при `JWT_REQUIRE_EXP=true`; по умолчанию бессрочные токены разрешены, но при наличии `exp` проверяется) |
| `iss`/`aud` | проверяются, только если заданы env `JWT_ISSUER`/`JWT_AUDIENCE`; если в токене есть iss/aud, а сервер их не задавал — ожидается совпадение с `app_name` |
| Leeway | `JWT_LEEWAY_S` (60 с) для exp/iat |
| Scopes | `rag:read`, `rag:index`, `rag:admin` (claims `scope`/`scopes`/`role`); **пусто = все права**; `rag:admin` implicite покрывает всё (`Principal.has`) |
| Ошибки | 401 (нет/плохой токен, заголовок `WWW-Authenticate: Bearer`, единое сообщение без деталей причины), 403 (недостаточно scope), 503 (контейнер ещё не готов) |

Генерация токена: `python tools/get_token.py --secret "$JWT_SECRET_KEY" [--sub n8n] [--ttl N]` — бессрочный токен со всеми scopes (без `exp`). Секрет: `python secret.py` (`secrets.token_urlsafe(48)`), min_length=32 контролируется Settings.

## Конфигурация (12-Factor)

- Только env/.env через `pydantic-settings` (`extra="ignore"`, case-insensitive), singleton `get_settings()` (`lru_cache`).
- python_test: `KB_ROOT`, `COMMON_DIR_NAMES` (CSV или JSON-список — кастомный `_split_comma_lists` + отключённый json.loads в источниках env), `OLLAMA_BASE_URL=http://ollama:11435/`, `EMBEDDING_MODEL=nomic-embed-text`, `EMBEDDING_DIM=768`, таймауты/backoff/retry, пул asyncpg (min 1/max 10, statement_timeout 60s), `COMPANY_PROFILES_JSON` (надёжная резолвинг-функция относительно корня сервиса).
- scheduler_service: `PORT=8200`, `CALLBACK_SECRET`, `N8N_WEBHOOK_URL`, `N8N_WEBHOOK_JWT_TOKEN`, интервалы воркера, DSN из `POSTGRES_*` или готового `DATABASE_URL` (нормализация `postgresql+asyncpg://`).
- `environment=production` → docs/openapi выключены; паттерн-валидация значения среды.

## DI / Composition Root

`Container.build(settings)` собирает: `Database` (asyncpg pool), `OllamaEmbeddingClient`, `KnowledgeBaseReader`, `_LazyRepository` (Proxy: репозиторий берёт живой пул у Database в момент вызова — можно собрать до подключения БД), `TaskRegistry`, `IndexingService`, `CompanyProfileRepository`, `CompanyProfilesService`, `CompanySearchService`. startup: connect → ensure_schema (RAG + company_profiles) → health-check Ollama (ok/degraded/down в лог); shutdown идемпотентен (`_closed`). Никакой нижний слой не импортирует container — подмена моками в тестах.

## Логирование и наблюдаемость

Формат `asctime | LEVEL | name | message`; `SensitiveDataFilter` маскирует `://user:pass@` и чувствительные ключи (password/secret/token/api_key/authorization/dsn) во **всех** логах; болтливые библиотеки — WARNING. Каждый SQL/Ollama-вызов логируется с направлением (`>>>`/`<<<`), длительностью и результатом. Health: `/live` (liveness), `/ready` (SELECT 1 + состояние Ollama/воркера) — без авторизации (для docker healthcheck).

## Обработка ошибок (presentation)

Иерархия `AppError{status_code, code, details}`: ConfigError/AuthError(401)/PermissionDeniedError(403)/TaskConflictError(409)/KnowledgeBaseError/IndexingError/EmbeddingError/DatabaseError(5xx) + специфичные (`TooFewCandlesError` 400 `not_enough_candles`, `PermanentEmbeddingError`). Глобальный handler → `{"code","message","details"}`. ASGI-middleware `SecurityHeadersMiddleware` добавляет `x-content-type-options: nosniff`, `x-frame-options: DENY`, `referrer-policy: no-referrer` (реализация без BaseHTTPMiddleware — не ломает streaming/фоновые задачи).

## Бизнес-правила инфраструктуры

1. Секреты никогда не попадают в код/логи/ответы ошибок; сообщения 401 намеренно не раскрывают причину.
2. Токен без scope трактуется как универсальный — осознанное упрощение проекта (документировано в security.py).
3. Все эндпоинты кроме `/live`,`/ready` (python_test), `/live`,`/ready` (scheduler) и `/callback` (секретный канал n8n) требуют JWT.
4. Порты: python_test 8100, scheduler 8200, ollama 11435, postgres 5432, n8n 5678, frontend 5173; bind-IP через env (`*_BIND_IP`, дефолт 127.0.0.1 кроме frontend).

## Паттерны

Service Locator (get_settings) + DI Container (явные зависимости сервисов), Proxy (_LazyRepository), Middleware (pure ASGI), Global Exception Handler, Defense-in-depth (маскирование логов + whitelist alg + compare_digest).

## Тесты

`test_security.py`, `test_config.py` (python_test), `test_callback_secret.py`, `test_config.py` (scheduler), `test_health.py`.
