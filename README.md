# RAG-индексатор базы знаний (OCR_Service)

Микросервис на **FastAPI**: читает «общие» JSON из `knowledge_base`, строит эмбеддинги
через **Ollama** и сохраняет документы с векторами в **PostgreSQL + pgvector**.
Даёт HTTP-API с Swagger для индексации, семантического поиска и статистики.

## Состав стека (docker-compose)

| Сервис        | Образ                     | Порт (хост) | Назначение                       |
|---------------|---------------------------|-------------|----------------------------------|
| `python_test` | локальная сборка          | `8100`      | RAG-индексатор (этот API)        |
| `postgres`    | `pgvector/pgvector:pg16`  | `5432`      | хранение документов и векторов   |
| `ollama`      | `ollama/ollama` (GPU)     | `11435`     | эмбеддинги                       |
| `n8n`         | `n8nio/n8n`               | `5678`      | автоматизация (машинные вызовы)  |

## Быстрый старт

```bash
# 1. Корневые переменные (порты, БД)
cp .env.example .env

# 2. Env микросервиса
cd python_test
cp .env.example .env
# сгенерировать JWT-секрет и вписать в .env (JWT_SECRET_KEY):
python ../secret.py

# 3. Поднять стек
cd ..
docker compose up -d --build

# 4. Сгенерировать ЕДИНЫЙ бессрочный токен (секрет = JWT_SECRET_KEY из python_test/.env)
python get_token.py --secret "<JWT_SECRET_KEY>"
```

Swagger: **http://localhost:8100/docs** → нажать **Authorize** → вставить токен
(только сам токен, без слова `Bearer`) → **Authorize** → выполнять запросы.

Проверка без Swagger:

```bash
TOKEN=$(python get_token.py --secret "<JWT_SECRET_KEY>" | head -1)
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8100/stats
```

## Авторизация: один бессрочный токен на всё

Схема максимально упрощена. **Админ-ключей (`ADMIN_API_KEY`), машинных ключей
(`API_KEYS` / `X-API-Key`) и эндпоинта `POST /auth/token` больше нет.**

Единственный канал доступа — JWT (HS256) в заголовке:

```
Authorization: Bearer <token>
```

Свойства токена:

* **Бессрочный** — генерируется без claim `exp`; сервер `exp` не требует
  (`JWT_REQUIRE_EXP=false`). Если `exp` всё же присутствует — он проверяется
  как обычно (просроченный токен отклоняется).
* **Универсальный по правам** — если в токене нет `scope`/`role`, ему даются
  все права (`rag:read`, `rag:index`, `rag:admin`). При желании можно ограничить:
  `--scope rag:read`.
* `iss`/`aud` по умолчанию **не проверяются** (`JWT_ISSUER`/`JWT_AUDIENCE` пустые).
  Токены со значениями `rag-indexer` (как выдавал старый код) тоже принимаются.

### Генерация токена

```bash
python get_token.py --secret "<JWT_SECRET_KEY>"                 # бессрочный, все права
python get_token.py --secret "<JWT_SECRET_KEY>" --sub n8n       # то же, с именем субъекта
python get_token.py --secret "<JWT_SECRET_KEY>" --scope rag:read --scope rag:index
python get_token.py --secret "<JWT_SECRET_KEY>" --ttl 3600      # если вдруг нужен TTL
```

Тот же токен используется в n8n (Http Request node → Header
`Authorization: Bearer <token>`) и в любых скриптах.

### Почему раньше был «токен не валидный» в Swagger

Наиболее частые причины (все устранены упрощением):

1. Токен истекал — `ACCESS_TOKEN_TTL_S=3600` выдавал токен на час, потом 401.
   Теперь токен бессрочный.
2. Проверялись `iss`/`aud` (`JWT_ISSUER/JWT_AUDIENCE=rag-indexer`) — токен без
   этих claims отвергался. Теперь по умолчанию они не проверяются.
3. В Swagger в поле Authorize вставляли вместе со словом `Bearer ` — теперь в UI
   прямо указано: только сам токен.
4. Секрет в env не совпадал с секретом, которым токен подписан (пересоздали
   `.env`, а старый токен остался) — подпись не сходится, 401. После смены
   секрета токен нужно перегенерировать.

## Конфигурация (`python_test/.env`)

| Переменная         | По умолчанию | Описание                                                        |
|--------------------|--------------|-----------------------------------------------------------------|
| `ENVIRONMENT`      | development  | `production` отключает `/docs`, `/redoc`, `/openapi.json`        |
| `LOG_LEVEL`        | INFO         | уровень логирования                                             |
| `JWT_SECRET_KEY`   | —            | **обязателен**, ≥32 символов; HS256-секрет подписи/проверки     |
| `JWT_ISSUER`       | пусто        | необязательно: ожидаемый `iss` (пусто = не проверять)           |
| `JWT_AUDIENCE`     | пусто        | необязательно: ожидаемый `aud` (пусто = не проверять)           |
| `JWT_REQUIRE_EXP`  | false        | требовать ли `exp` во входящем токене                            |
| `JWT_LEEWAY_S`     | 60           | допуск часовых поясов при проверке `exp`/`iat`, сек             |
| `POSTGRES_*`       | —            | доступ к БД (должны совпадать с корневым `.env`)                |
| `OLLAMA_BASE_URL`  | http://ollama:11435 | адрес Ollama внутри сети compose                          |
| `EMBEDDING_MODEL`  | nomic-embed-text | модель эмбеддингов                                          |
| `EMBEDDING_DIM`    | 768          | размерность вектора                                             |
| `KB_ROOT`          | /app/knowledge_base | корень базы знаний внутри контейнера                     |

## API

Открытые (без токена): `GET /live`, `GET /ready`.

| Метод/путь                        | Scope      | Описание                                    |
|-----------------------------------|------------|---------------------------------------------|
| `POST /index`                     | rag:index  | запустить фоновую индексацию knowledge_base |
| `GET  /index/tasks`               | rag:read   | список последних задач                      |
| `GET  /index/tasks/{task_id}`     | rag:read   | статус/прогресс задачи                      |
| `POST /index/tasks/{task_id}/cancel` | rag:admin | отменить задачу                           |
| `POST /search`                    | rag:read   | семантический поиск (top_k по косинусу)     |
| `GET  /documents`                 | rag:read   | проиндексированные концепты                 |
| `GET  /sources`                   | rag:read   | файлы KB и число концептов (без БД)         |
| `GET  /stats`                     | rag:read   | статистика индекса                          |

Формат ошибок единый: `{"code": "...", "message": "...", "details": {...}}`.

## Структура репозитория

```
├── docker-compose.yml        # ollama + postgres + n8n + rag-индексатор
├── .env.example              # корневой env для compose (порты, БД)
├── init_db/01_init_rag.sql   # создание схемы pgvector при первом старте
├── get_token.py              # генератор бессрочного JWT (единственный способ получить токен)
├── secret.py                 # генератор JWT_SECRET_KEY
└── python_test/
    ├── Dockerfile
    ├── requirements.txt
    ├── .env.example          # env микросервиса (копировать в .env)
    ├── knowledge_base/       # исходные JSON
    └── app/
        ├── main.py           # FastAPI, middleware, OpenAPI (security = Bearer JWT)
        ├── container.py      # composition root (DI)
        ├── core/             # config (pydantic-settings), security (JWT), logging, errors
        ├── api/routes/       # health, rag
        ├── services/         # чтение KB, индексация
        ├── clients/          # Ollama embedder
        ├── db/ , repositories/  # asyncpg + pgvector
        └── workers/          # реестр фоновых задач
```

## Разработка локально (без Docker)

```bash
cd python_test
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                      # заполнить POSTGRES_*, JWT_SECRET_KEY
uvicorn app.main:app --reload --port 8100
```

Нужны доступные PostgreSQL с pgvector и Ollama (например, из `docker compose up postgres ollama`).

## Полезно знать

* `.env` нигде не коммитится (см. `.gitignore`) — в git только `.env.example` с плейсхолдерами.
* Смена `JWT_SECRET_KEY` мгновенно инвалидирует все ранее выданные токены — перегенерируйте токен.
* Бессрочный токен = постоянный секрет в клиенте. Это осознанный компромисс для закрытой LAN;
  при выходе в интернет лучше включить `JWT_REQUIRE_EXP=true` и выдавать токены с TTL.
* ОdinTochniy токен подходит и Swagger'у, и n8n, и curl — различий между клиентами больше нет.
