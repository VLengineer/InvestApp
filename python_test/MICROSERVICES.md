# Как добавлять микросервисы в python_test

Каждый новый микросервис получает **свою папку внутри `python_test/`** — код
(repositories / services / schemas) живёт там, а HTTP-эндпоинты подключаются
**отдельным файлом в `app/api/routes/`**. Общий слой (`app/core`, `app/db`,
`app/api/deps.py`, `app/container.py`) переиспользуется.

## Шаг за шагом (на примере `news_analyzer`)

1. **Создать папку микросервиса**: `python_test/<имя_сервиса>/`
   ```
   python_test/news_analyzer/
       __init__.py      # экспорт публичных классов пакета
       schemas.py       # pydantic-модели (контракт API)
       client.py        # HTTP-клиенты внешних сервисов (пример: n8n webhook)
       repository.py    # (опционально) работа с БД (asyncpg, пул из app.db.database.Database)
       service.py       # бизнес-логика
   ```

2. **Подключить к DI-контейнеру** (`app/container.py`): добавить поля и сборку
   в `Container.build(...)`, при необходимости — `ensure_schema()` в `startup()`.

3. **Добавить зависимости API** (`app/api/deps.py`): геттеры + `Annotated`-алиасы
   (например `NewsAnalyzerDep`).

4. **Создать файл роутов**: `app/api/routes/<имя>.py` (например `news.py`) с
   `router = APIRouter(prefix="/<имя>", tags=["<имя>"])`; авторизация — единый
   JWT через `require_scope(Scope.*)`.

5. **Зарегистрировать роутер** в `app/api/routes/__init__.py`:
   ```python
   from app.api.routes import health, news, rag
   api_router.include_router(news.router)
   ```

6. **Dockerfile**: скопировать папку сервиса в образ рядом с остальными:
   ```dockerfile
   COPY news_analyzer ./news_analyzer   # + новая строка для каждого микросервиса
   ```

7. **Схема БД** (если нужны таблицы): SQL-файл `init_db/NN_<имя>.sql` для
   первичной инициализации postgres. Если сервис сам работает с БД — добавить
   идемпотентный DDL в `ensure_schema()` своего репозитория; если записи пишет
   внешний пайплайн (как news_analyzer → n8n), достаточно init-скрипта.

8. `.env` микросервиса (`python_test/.env`) — общие настройки; специфичные
   переменные добавляйте в `Settings` (`app/core/config.py`). Внешние адреса
   (например путь вебхука n8n: `N8N_BASE_URL` + `N8N_NEWS_WEBHOOK_PATH`) —
   только через env, не хардкодом.

## Текущие микросервисы

| Папка кода                       | Файл эндпоинтов            | Эндпоинты                                   | Что делает                  |
|----------------------------------|----------------------------|---------------------------------------------|-----------------------------|
| `app/` (RAG-индексатор, общий)   | `app/api/routes/rag.py`    | `/index`, `/run`, `/search`, `/stats`, …    | таблицы `kb_documents`, `kb_embeddings` |
| `news_analyzer/`                 | `app/api/routes/news.py`   | `POST /news/analyze`, `GET /news/health`    | пересылает новость на вебхук n8n (в БД НЕ пишет) |

Цепочка анализа новостей: фронтенд Vue (`frontend/`, контейнер `frontend`) или
другой клиент отправляет JSON `{source, title, content, ts}` на вебхук n8n
`http://n8n:5678/webhook/news_analizer`; сценарий n8n может вызвать
`POST http://python_test:8100/news/analyze` (с JWT) — тот вернёт этот же JSON
и перешлёт его на вебхук (URL берётся из env `N8N_BASE_URL` +
`N8N_NEWS_WEBHOOK_PATH`, см. `python_test/.env`). Сохранением записей в
`market_news_ml_dataset` (DDL: `init_db/02_init_market_news_ml.sql`) занимается
сам сценарий n8n.
