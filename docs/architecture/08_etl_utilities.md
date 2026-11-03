# Сервис 8. ETL-утилиты подготовки данных (CLI)

**Реализация:** вне HTTP — скрипты и данные репозитория
**Ключевые модули:**
- `python_test/knowledge_base/build_kb.py` (+ `merge_kb.py`) — сборка/валидация базы знаний
- `scripts/load_company_profiles.py` — CLI-ингест cp.json (зеркало сервиса 03)
- `tools/get_token.py`, `secret.py` — генерация JWT/секретов (см. сервис 07)
- `Инструменты Т-инвест.json` — статичный DUMP каталога инструментов T-Invest API
- `python_test/embeddings/` (`embeddings.py`, `config.py`, `ollama_client.py`, `test_ollama.py`) — legacy-пакет эмбеддингов (синхронный `ollama.Client`, `/api/embeddings` + `_fit_dim`); в рантайме FastAPI-сервисов **не используется** (есть асинхронный `app/clients/ollama.py`)
- `frontend/src/lib/api.ts` — клиент эндпоинтов планировщика для UI n8n

## 8.1. Сборщик базы знаний `build_kb.py`

**Назначение:** обходит все подпапки `knowledge_base/`, проверяет структуру JSON-концептов, собирает валидные в единый `kb_all.json` (плоский список) + отчёт; приложение по умолчанию индексирует только папки «Общий json», поэтому merged-файл — способ проиндексировать всё (`COMMON_DIR_NAMES=[]` или `KB_ROOT=.../knowledge_base_merged`).

Использование: `python3 build_kb.py [--check] [--strict] [--output F] [--dedup id+hash] [--fix-control-chars] [--require-fields ...]`. Код возврата: 0 — ок, 1 — битые JSON при `--strict`, 2 — ошибка аргументов/пути.

Правила: чтение `utf-8-sig` (BOM); опциональная починка управляющих символов внутри строк (сырые `\n/\t/"` ломают json.loads и PostgreSQL jsonb); обязательные поля концепта — `id` (или name/title) + `title`, рекомендуемые — category/essence/formula/…; дедупликация по id/hash; запуск из любой папки (пути относительно скрипта).

Ошибки: нечитаемый файл → попадает в отчёт с причиной, сбор продолжается.

## 8.2. CLI-загрузчик профилей `load_company_profiles.py`

Делает ровно то же, что `POST /company-profiles/ingest`, но из командной строки: читает `cp.json` (arg `--json`, дефолт `company_profiles/cp.json`), формирует склеенный текст по приоритету полей (как сервис 03), получает вектор через **прямой HTTP** `POST {OLLAMA_BASE_URL}api/embed` (`{"model","input"}`, ожидание `embeddings|embedding`), upsert-ит в PostgreSQL.

Отличия от HTTP-эндпоинта: модель берётся из env `EMBEDDING_MODEL` (дефолт в комментарии — embeddinggemma-2, тогда как Settings приложения — nomic-embed-text); проверка размерности предупреждением, а не ошибкой breaker'а; секреты из `.env` python_test. Используется для первичного наполнения/отладки без JWT.

Ошибки: отсутствующий cp.json → stderr + exit≠0; ошибка эмбеддинга одного профиля — continue со счётчиком failed (логика зеркалируется с сервисом).

## 8.3. DUMP «Инструменты Т-инвест.json»

Снапшот ответа `GetAllInstruments` Tinkoff Invest API: массив `{"json": {"instruments": [{figi, ticker, classCode, isin, lot, currency, name, exchange, sector, countryOfRisk, buyAvailable/sellAvailable, price, floatSize, apiTradeAvailableFlag, createDate, …}]}}` (~1 МБ).

**Потребители кода: отсутствуют** (проверено поиском по репозиторию) — это эталонные/обучающие данные формата инструмента (ключи `units/nano` совпадают с контрактом сервиса 05) и сырьё для ML-датасета `market_news_ml_dataset` (DDL — `init_db/02_init_market_news_ml.sql`; код news_analyzer в ветке отсутствует; сам датасет читает BFF дашборда `backend-frontend` — документ 09). Правила актуальности: ручное обновление снапшота; идентификатор жизни записи — `figi`.

## 8.4. Legacy-пакет `python_test/embeddings/`

Модуль `EmbeddingClient` (синхронный SDK ollama, эндпоинт `embeddings(prompt=...)`) с приведением размерности `_fit_dim` (усечение+ренормировка либо zero-padding) — историческая версия клиента до перехода на REST `/api/embed` в `app/clients/ollama.py`; содержит собственный `config.py` (pydantic-settings, `ENV_FILE`). В Docker-образ приложения не входит (`COPY app ./app`). `test_ollama.py` — smoke-скрипт проверки модели. Риск: расхождение dim-политики (legacy молча подгоняет вектор, основной клиент — жёстко отвергает ≠768).

## Безопасность утилит

Секреты только из env/.env; `get_token.py` печатает токен в stdout (одноразовая операция админа); CLI-загрузчик требует прямого доступа к БД/Ollama — запускаться только из доверенного окружения docker-сети.

## Паттерны

Idempotent ETL (UPSERT/dedup), Report-and-continue (битые элементы не останавливают пакет), Config-from-env, dry-run режимы (`--check`).

## Тесты

Юнит-тестов CLI нет; `build_kb.py --check` выполняет роль self-test данных; `embeddings/test_ollama.py` — ручной smoke Ollama.
