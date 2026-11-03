# Сервис 1. RAG-пайплайн индексации базы знаний

**Реализация:** микросервис `python_test` (FastAPI, порт 8100)
**Ключевые модули:**
- `python_test/app/api/routes/rag.py` — эндпоинты `/index`, `/run`, `/index/tasks*`
- `python_test/app/services/indexing_service.py` — оркестрация конвейера
- `python_test/app/services/kb_reader.py` — обнаружение и чтение JSON базы знаний
- `python_test/app/services/domain.py` — доменная модель `Concept`, хеширование, сборка текста
- `python_test/app/repositories/document_repository.py` — единственный модуль, знающий SQL
- `python_test/app/clients/ollama.py` — эмбеддинг-клиент (Circuit Breaker + Retry)
- `python_test/app/workers/task_registry.py` — in-memory реестр фоновых задач
- `init_db/01_init_rag.sql` / `python_test/app/db/database.py` — DDL (`kb_documents`, `kb_embeddings`)

## Назначение

Преобразует файлы базы знаний (`knowledge_base/**/*.json`, концепты с полями `id`+`title`) в векторный индекс: каждый концепт → эмбеддинг Ollama (768d) → атомарная запись пары «документ + вектор» в PostgreSQL+pgvector. Индексация выполняется **фоновой задачей** с наблюдаемым прогрессом и защитой от дублей.

## API контракты

### POST `/index` — запуск индексации (scope `rag:index`)
Тело (`IndexOptions`, `extra="forbid"`):

| Поле | Тип | Default | Описание |
|---|---|---|---|
| `dry_run` | bool | false | Посчитать план без обращений к Ollama/БД |
| `force_reindex` | bool | false | Пересоздать эмбеддинги даже при совпадении `content_hash` |
| `limit_documents` | int\|null | null (ge=1) | Отладочный лимит числа концептов; **не указывать для полной индексации** |
| `source_paths` | list[str]\|null | null | Фильтр по относительным путям из `GET /sources`; пути нормализуются (срезание префиксов `/app/knowledge_base/`, `knowledge_base/`, `./`) |

Ответ `202` (`IndexAcceptedResponse`): `task_id: UUID`, `status: TaskStatus`, `documents_found: int` (файлов), `concepts_planned: int` (к обработке), `message: str` (план + предупреждение о применённом limit).
Одновременно может выполняться только одна индексация — иначе `409` (`TaskConflictError`).

### POST `/run` — полная индексация одним вызовом (scope `rag:index`)
Тело необязательное (`RunRequest`): `force_reindex: bool = false`.
Ответ `202` (`RunAcceptedResponse`): `task_id`, `status`, `files_found`, `concepts_total`, `unique_concepts`, `already_indexed`, `to_embed`, `message`.
Повторный вызов безопасен: досчитывает только незагруженное (см. «Правила»).

### GET `/index/tasks?limit=20` — последние задачи (scope `rag:read`), 1..100
### GET `/index/tasks/{task_id}` — статус/прогресс задачи (scope `rag:read`)
Ответ `TaskView`: `task_id, status(pending|running|succeeded|failed|cancelled), started_at, finished_at, total, processed, embedded, stored_documents, skipped_duplicates, failed, errors[]` (до 50 образцов `{where, error}`).
### POST `/index/tasks/{task_id}/cancel` — отмена (scope `rag:admin`); 404 если задача неизвестна.

## Модель данных

```sql
kb_documents(document_id uuid PK, source_path text, concept_id text, title text,
             category text, payload jsonb, content_hash char(64) UNIQUE, indexed_at timestamptz)
kb_embeddings(embedding_id bigint PK, document_id uuid FK→kb_documents ON DELETE CASCADE,
              chunk_index int DEFAULT 0, model text, embedding vector(768), created_at,
              UNIQUE(document_id, chunk_index, model))
```
Индексы: уникальный по `content_hash` (глобальная детекция дублей), по `concept_id`, `source_path`, FTS-gin по `title` ('russian').

## Бизнес-правила

1. **Отбор файлов:** читаются только JSON внутри папок `common_dir_names` (default `["Общий json"]`); если фильтр ничего не нашёл — fallback на все `*.json` рекурсивно с WARNING в лог. Симлинки наружу и `desktop.ini` отбрасываются; лимиты: файл ≤ 20 MiB, чанк ≤ 8000 симв. (`max_chunk_chars`).
2. **Извлечение концептов:** рекурсивный обход любой вложенности; концепт = dict с обязательными `id`+`title`; `title` обрезается до 512, `category` до 256 символов.
3. **Текст для эмбеддинга:** склейка значимых полей (`title, category, essence, formula, interpretation, sector_specifics, limitations, related_concepts, search_keywords, source_text_excerpt`) в формате `key: value`, префикс `doc: `, усечение до `max_chunk_chars`.
4. **Детекция дублей:** `content_hash = sha256(canonical_json(concept))` (sort_keys, separators `(",",":")`); дедупликация внутри запуска по hash; пропуск уже проиндексированных = hash присутствует в `kb_documents` И есть эмбеддинг **текущей модели** в `kb_embeddings` (иначе — реэмбеддинг).
5. **`limit_documents` применяется ПОСЛЕ** подсчёта summary: в ответе видны и полный план (`to_embed_full`), и лимит.
6. **Гонка `/run`:** сначала dry-run того же плана (не занимает слот реестра), полноценная задача создаётся только если `to_embed > 0`.
7. **Пустой план ≠ ошибка:** задача сразу `succeeded`, в лог — явная диагностика причин (уже проиндексировано / фильтры съели всё / битые файлы).
8. **Защитный стоп:** 10 неуспешных концептов подряд → задача `FAILED` («проверьте доступность Ollama и PostgreSQL»).
9. **Статус задачи:** `FAILED` только если есть ошибки И ни одного сохранённого документа; иначе `SUCCEEDED` (частичные ошибки видны в `errors[]`/`failed`).
10. **Идемпотентность записи:** UPSERT по `content_hash` (`ON CONFLICT DO UPDATE ... RETURNING document_id, (xmax=0) AS inserted`) + UPSERT эмбеддинга по `(document_id, chunk_index, model)` — повторные прогоны не создают дублей.
11. **Размерность:** вектор ≠ 768 → ошибка до отправки в БД (`DatabaseError`), попытка считается сбоем breaker'а.

## Обработка ошибок

| Ситуация | Реакция |
|---|---|
| Параллельная индексация | HTTP 409 `TaskConflictError` |
| Файл knowledge_base битый JSON | источник помечается `error`, чтение продолжается с остальными файлами; список — в `summary.files_with_errors` + WARNING |
| Ошибка эмбеддинга концепта | `task.add_error("embedding:<id>")`, переход к следующему |
| Ошибка записи в БД | `task.add_error("store:<id>")`, переход к следующему |
| HTTP 4xx от Ollama (модель не загружена) | `PermanentEmbeddingError` — retry/breaker пропускаются, ошибка сразу наружу |
| Сетевые ошибки Ollama | exponential backoff с jitter (base 0.5s, max 20s, до `max_retries=4`), затем EmbeddingError |
| Circuit breaker OPEN (≥ threshold подряд) | быстрый отказ с `retry_after_s` |
| Cancel | `asyncio.CancelledError` → статус `cancelled`, слот освобождается |

## Безопасность

Все эндпоинты — JWT Bearer + scope (`rag:index` для записи, `rag:read` для чтения, `rag:admin` для cancel). Секрет только из env; логи маскируются (`SensitiveDataFilter`). Путь traversal защищён проверкой `resolve().is_relative_to(kb_root)`.

## Паттерны

DI (Composition Root `container.py`, `_LazyRepository` — Proxy к живому пулу), Facade (`IndexingService`), Strategy (политика отбора файлов в `KnowledgeBaseReader._is_common_json`), Repository (весь SQL в одном модуле), Producer–consumer с mutex-реестром задач, Circuit Breaker + Retry (Ollama), Unit of Work (транзакция UPSERT).

## Тесты

`python_test/app/tests/test_run_endpoint.py` — поведение `POST /run` (в т.ч. отсутствие дублей при повторном вызове).
