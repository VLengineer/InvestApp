# Архитектурная документация проекта

**Дата актуальности:** 2026-11-04
**Стек:** Python 3.12 / FastAPI / asyncpg + PostgreSQL 16 (pgvector) / Ollama (эмбеддинги, 768d) / n8n / Vue 3 + TypeScript (Vite) / Docker Compose (сеть `app_net`)

Проект — это три FastAPI-микросервиса, SPA-дашборд и вспомогательные ETL-утилиты, сгруппированные ниже в **логические сервисы** (доменные области). Один микросервис (`python_test`, порт 8100) содержит сразу несколько логических сервисов; `scheduler_service` (порт 8200) — отдельный процесс с фоновым воркером; `backend-frontend` (порт 8300) — BFF финансового дашборда (REST + WebSocket), обслуживающий SPA `frontend` (Vite dev-server, порт 5173).

## Реестр логических сервисов

| # | Логический сервис | Файл документации | Основные эндпоинты / точки входа | Хранилище |
|---|---|---|---|---|
| 1 | RAG-пайплайн индексации базы знаний | [01_rag_indexing_pipeline.md](01_rag_indexing_pipeline.md) | `POST /index`, `POST /run`, `GET /index/tasks*`, `POST /index/tasks/{id}/cancel` | `kb_documents`, `kb_embeddings` |
| 2 | Сервис семантического поиска по базе знаний | [02_rag_semantic_search.md](02_rag_semantic_search.md) | `POST /search`, `GET /documents`, `GET /sources`, `GET /stats` | `kb_documents`, `kb_embeddings` |
| 3 | Сервис профилей компаний (ingest + хранение) | [03_company_profiles_service.md](03_company_profiles_service.md) | `POST /company-profiles/ingest`, `GET /company-profiles`, `GET /company-profiles/{figi}`, `POST /company-profiles/search` | `company_profiles` |
| 4 | Сервис анализа новостей (поиск эмитентов по тексту новости) | [04_news_company_search.md](04_news_company_search.md) | `CompanySearchService.search_by_news` (контракт `POST /news/search-companies`) | `company_profiles` (чтение) |
| 5 | Сервис технического анализа свечей (формат T-Invest API) | [05_indicators_ta_service.md](05_indicators_ta_service.md) | `POST /indicators/calculate` | нет (stateless, in-memory) |
| 6 | Сервис-планировщик интеграции с n8n (очередь задач + callback) | [06_scheduler_n8n_service.md](06_scheduler_n8n_service.md) | `POST /api/v1/scheduler/start|stop`, `GET /state`, `POST /callback`, `GET /tasks/{id}` + background worker | `scheduler_state`, `tasks` |
| 7 | Инфраструктурный слой: безопасность, DI, конфигурация | [07_infrastructure_security.md](07_infrastructure_security.md) | сквозная зависимость всех сервисов (`Authorization: Bearer JWT`) | env / `.env` |
| 8 | ETL-утилиты подготовки данных | [08_etl_utilities.md](08_etl_utilities.md) | CLI: `build_kb.py`, `scripts/load_company_profiles.py`, `tools/get_token.py`; данные: `Инструменты Т-инвест.json` | файлы / `company_profiles` |
| 9 | BFF финансового дашборда + SPA `frontend` | [09_bff_frontend_dashboard.md](09_bff_frontend_dashboard.md) | `GET /api/market/figis|initial-data|news/{id}`, WS `/ws/market-updates`, `GET /live|/ready`; Swagger `:8300/docs`; SPA: Vite-dev-proxy `/api/*`, `/ws` (порт 5173) | `market_news_ml_dataset` (чтение) |

## Сквозная архитектура (top-level)

```
 frontend (Vue3+TS SPA, Vite 5173)                     n8n (webhooks)
   │  REST /api/market/*, WS /ws/market-updates          ▲
   ▼  (через vite-dev-proxy MARKET_API_PROXY_TARGET)     │ callback (X-Callback-Secret)
 backend-frontend (BFF, FastAPI :8300) ──────────────────┘   POST /api/v1/scheduler/callback
   │  asyncpg (чтение market_news_ml_dataset)                  ▲
   ▼                                                           │ worker: очередь tasks
 PostgreSQL (vectordb, pgvector) ◀── polling статуса ── scheduler_service (8200)
   ▲        ┌── POST вебхук start_process {"task_id": uuid} ───┘
   │        │
 python_test (8100): rag / company-profiles / indicators / news-search ─┤
   │                                                                    │
   ▼                                                                    │
 Ollama (nomic-embed-text / embeddinggemma-2, 768d) ◀───────────────────┘
```

## Общие конвенции

- **Единый токен доступа:** один JWT HS256 (`JWT_SECRET_KEY`) на все сервисы; scopes `rag:read` / `rag:index` / `rag:admin`; токен без scope = все права (детали — документ 07). **Исключение:** BFF `backend-frontend` (:8300) работает без авторизации — наружу проброшен только на `127.0.0.1` (`MARKET_BIND_IP`), доступ к нему — через Vite-dev-proxy SPA (документ 09).
- **Формат ошибок:** доменные `AppError` → `{"code", "message", "details"}` (exception handler в `app/main.py`).
- **Слои внутри каждого сервиса:** `routes → services → repositories → БД`; граф зависимостей собирается в Composition Root (`app/core/container.py`). У `backend-frontend` упрощённая вариация тех же слоёв (`api/routes → services → repositories → asyncpg`, DI через `Annotated`-провайдеры в `app/api/deps.py`).
- **Эмбеддинги:** промпт-формат модели — префикс `doc:` для индексируемого текста, `search:` для запроса; размерность строго 768.

## Известные расхождения кода и окружения (зафиксировано при анализе)

1. **Нет активного роутера `/news/search-companies`:** сервис `CompanySearchService` собран в DI-контейнере и имеет dependency-провайдер `CompanySearchDep` (`app/api/deps.py`), но ни один включённый в `api_router` роутер его не использует — HTTP-эндпоинт на текущей ветке не опубликован (см. документ 04).
2. **Модель эмбеддинга в проде vs комментарии:** `Settings.embedding_model = "nomic-embed-text"` (env-переопределяемый), тогда как в комментариях/скриптах фигурирует `hf.co/unsloth/embeddinggemma-2-GGUF:UD-Q6_K_XL`. Размерность одинаковая (768), но смешивание моделей в одной таблице ломает сравнимость векторов (`kb_embeddings` защищено фильтром `WHERE model = $`, а `company_profiles` — только колонкой `embedding_model` без фильтра в поиске).
3. **DUMP «Инструменты Т-инвест.json»** — статичный снапшот ответа GetAllInstruments Tinkoff Invest API; ни один модуль кода его не читает (сырьё для ML-датасета `market_news_ml_dataset`, DDL которого присутствует в `init_db/02_init_market_news_ml.sql`). Микросервис-анализатор новостей (`news_analyzer`), который наполнял бы этот датасет и поле `ai_raw_response`, в текущей ветке отсутствует — `backend-frontend` выступает только читателем готовых данных (см. документ 09).
4. **Написание поля `ai_raw_responce` vs `ai_raw_response`:** исторически в ТЗ/домах колонка фигурировала с опечаткой (`responce`); каноническое имя в схеме БД и Pydantic-схеме BFF — `ai_raw_response`. Frontend толерантен к обоим написаниям (`types/market.ts`, `AICard.vue`: `item.ai_raw_response ?? item.ai_raw_responce`).
5. **Тесты `backend-frontend` требуют env:** `Settings` обязательны `POSTGRES_USER`/`POSTGRES_PASSWORD`; вне контейнера (где они приходят из `backend-frontend/.env`) pytest падает на collection с `ValidationError` — при локальном запуске задавайте их явно.
