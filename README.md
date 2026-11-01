# OCR_Service — RAG-индексатор базы знаний

Локальный стек для семантического поиска по базе знаний (JSON-концепты) без облаков:
**FastAPI (RAG-индексатор + Swagger) + PostgreSQL/pgvector + Ollama (GPU, эмбеддинги) + n8n**.

## Архитектура и порты

| Сервис        | Что делает                                           | Порт хоста          | Swagger                      |
|---------------|------------------------------------------------------|---------------------|------------------------------|
| `ollama`      | Модель эмбеддингов `nomic-embed-text` (GPU nvidia)   | `11435`             | —                            |
| `postgres`    | Хранение документов и векторов (pgvector)            | `127.0.0.1:5432`    | —                            |
| `n8n`         | Low-code автоматизация, вызывает RAG через X-API-Key | `5678` (0.0.0.0)    | —                            |
| `python_test` | Микросервис индексации и поиска (FastAPI)            | `127.0.0.1:8100`    | http://localhost:8100/docs   |

Порты уже настроены как надо — не меняйте их в `.env` без необходимости.

## Структура проекта

```
.
├── docker-compose.yml        # весь стек (ollama GPU, postgres, n8n, rag)
├── .env.example  →  .env     # переменные compose (БД, порты, URL n8n)
├── init_db/                  # SQL, автоматически применяется при ПЕРВОМ старте postgres
│   └── 01_init_rag.sql       # расширения vector/pgcrypto, таблицы kb_documents, chunks, tasks
├── python_test/              # микросервис RAG-индексатора
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .env.example → .env   # секреты приложения (JWT, API-ключи, доступ к БД/Ollama)
│   ├── app/                  # FastAPI: routes, services, db, security
│   └── knowledge_base/       # исходные JSON-файлы базы знаний (внутри образа)
└── README.md
```

## Быстрый старт

Требования: Docker + Docker Compose, NVIDIA Driver + Container Toolkit (для GPU Ollama).

```bash
# 1. Создать env-файлы из примеров
cp .env.example .env
cp python_test/.env.example python_test/.env

# 2. Заполнить секреты в python_test/.env (ОБЯЗАТЕЛЬНО):
#    JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
#    ADMIN_API_KEY / API_KEYS — свои значения (см. ниже), POSTGRES_* = из корневого .env

# 3. Поднять стек
docker compose up -d --build

# 4. Скачать модель эмбеддингов (один раз)
docker exec ollama ollama pull nomic-embed-text

# 5. Проверить готовность
curl http://localhost:8100/ready
```

Открыть Swagger: **http://localhost:8100/docs** · n8n: **http://localhost:5678**

## Переменные окружения

### Корневой `.env` (подстановка в docker-compose.yml)

| Переменная                                | Пример                     | Назначение                              |
|-------------------------------------------|----------------------------|-----------------------------------------|
| `POSTGRES_USER`                           | `rag_user`                 | Пользователь БД                         |
| `POSTGRES_PASSWORD`                       | `rag_local_password`       | Пароль БД                               |
| `POSTGRES_DB`                             | `vectordb`                 | Имя БД                                  |
| `POSTGRES_PORT`                           | `5432`                     | Порт БД на хосте (только 127.0.0.1)     |
| `OLLAMA_PORT`                             | `11435`                    | Порт Ollama                             |
| `N8N_PORT` / `N8N_BIND_IP`                | `5678` / `0.0.0.0`         | Доступ к n8n в локальной сети           |
| `N8N_EDITOR_BASE_URL` / `N8N_WEBHOOK_URL` | `http://192.168.0.5:5678/` | Публичные URL n8n (IP хоста в LAN)      |
| `RAG_PORT` / `RAG_BIND_IP`                | `8100` / `127.0.0.1`       | Доступ к RAG-сервису                    |
| `TZ`                                      | `Europe/Moscow`            | Часовой пояс n8n                        |

### `python_test/.env` (настройки приложения)

| Переменная                          | Назначение                                                              |
|-------------------------------------|-------------------------------------------------------------------------|
| `ENVIRONMENT`                       | `development` (Swagger открыт) / `production` (`/docs` отключён)        |
| `JWT_SECRET_KEY`                    | Секрет подписи JWT (HS256), ≥ 32 символов, сгенерировать свой           |
| `ADMIN_API_KEY`                     | Ключ, разрешающий выдачу JWT через `POST /auth/token`                   |
| `API_KEYS`                          | JSON-список машинных ключей `X-API-Key` для n8n и внутренних сервисов   |
| `ACCESS_TOKEN_TTL_S`                | Время жизни JWT, сек (по умолчанию 3600)                                |
| `POSTGRES_HOST`                     | `postgres` (имя сервиса внутри compose)                                 |
| `OLLAMA_BASE_URL`                   | `http://ollama:11435`                                                   |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | `nomic-embed-text` / `768`                                              |
| `KB_ROOT`                           | `/app/knowledge_base` — каталог JSON-файлов внутри контейнера           |

> Значения `POSTGRES_USER/PASSWORD/DB` в `python_test/.env` **должны совпадать** с корневым `.env`.

## Безопасность и работа со Swagger («как положено»)

В Swagger (`/docs`) есть кнопка **Authorize** с двумя схемами:

- **BearerJWT** — JWT-токен из `POST /auth/token`;
- **ApiKeyHeader** — машинный ключ `X-API-Key` (из `API_KEYS`).

Получить JWT:

```bash
curl -X POST http://localhost:8100/auth/token \
  -H "X-API-Key: <ADMIN_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"subject": "n8n", "scopes": ["rag:read", "rag:index"]}'
```

Затем нажмите **Authorize** и вставьте токен (или передавайте его в заголовке
`Authorization: Bearer <token>`). Для машинных вызовов из n8n достаточно заголовка
`X-API-Key: <ключ из API_KEYS>`. Эндпоинты `/live` и `/ready` открыты без авторизации.

## Основные эндпоинты RAG-сервиса

| Метод | Путь                            | Описание                                   |
|-------|---------------------------------|--------------------------------------------|
| POST  | `/auth/token`                   | Выдача JWT (`subject`, `scopes`: rag:read / rag:index / rag:admin) |
| POST  | `/index`                        | Запуск фоновой индексации `knowledge_base` |
| GET   | `/index/tasks`                  | Список задач индексации                    |
| GET   | `/index/tasks/{task_id}`        | Статус задачи                              |
| POST  | `/index/tasks/{task_id}/cancel` | Отмена задачи                              |
| POST  | `/search`                       | Семантический поиск по векторам            |
| GET   | `/documents`                    | Список проиндексированных документов       |
| GET   | `/sources`                      | Файлы-источники базы знаний                |
| GET   | `/stats`                        | Статистика БД (документы, чанки, векторы)  |
| GET   | `/live`, `/ready`               | Healthcheck (без авторизации)              |

## Типовой сценарий использования

```bash
# 1. Индексировать базу знаний (новые JSON кладутся в python_test/knowledge_base,
#    после чего образ пересобирается: docker compose up -d --build python_test)
curl -X POST http://localhost:8100/index -H "X-API-Key: <API_KEY>"

# 2. Дождаться завершения (статус задачи)
curl http://localhost:8100/index/tasks/<task_id> -H "X-API-Key: <API_KEY>"

# 3. Искать
curl -X POST http://localhost:8100/search -H "X-API-Key: <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"query": "что такое RSI", "top_k": 5}'
```

Дубликаты концептов отсекаются по SHA-256 содержимого (`content_hash`), повторная
индексация безопасна (идемпотентна).

## Подключение к n8n

В n8n используйте ноду **HTTP Request**:

- URL: `http://python_test:8100/search` (внутри сети compose) или `http://<IP-хоста>:8100/search` (снаружи);
- Заголовок: `X-API-Key: <ключ из API_KEYS>`;
- Тело (JSON): `{ "query": "...", "top_k": 5 }`.

Вебхуки n8n доступны по адресу `N8N_WEBHOOK_URL` (`http://192.168.0.5:5678/webhook/...`).

## Полезные команды

```bash
docker compose ps                                        # статус контейнеров
docker compose logs -f python_test                       # логи RAG-сервиса
docker compose logs -f ollama                            # логи Ollama
docker exec ollama ollama list                           # скачанные модели
docker exec -it postgres psql -U rag_user -d vectordb    # зайти в БД
docker compose down                                      # остановить (данные volume сохранятся)
docker compose down -v                                   # УДАЛИТЬ вместе с данными БД и volume
```

## Устранение неполадок

- **Ollama не стартует** — проверьте `nvidia-smi` и установленный NVIDIA Container Toolkit; порт `11435` не должен быть занят.
- **`/ready` возвращает 503** — БД или Ollama недоступны; смотрите `docker compose logs`.
- **Ошибка 401/403** — не совпадают ключи: проверьте `API_KEYS`/`ADMIN_API_KEY` в `python_test/.env` и заголовок `X-API-Key`; протухший JWT — запросите новый токен.
- **Пустая выдача из `/search`** — база не индексирована: выполните `POST /index` и дождитесь статуса `completed`.
- **Изменили пароли БД после первого запуска** — init-скрипты и подстановка применяются только при создании volume: `docker compose down -v && docker compose up -d --build` (данные будут потеряны).
- **Swagger недоступен** — проверьте `ENVIRONMENT=development` в `python_test/.env` (в production `/docs` отключён намеренно).
