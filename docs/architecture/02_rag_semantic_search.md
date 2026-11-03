# Сервис 2. Семантический поиск по базе знаний (RAG search)

**Реализация:** микросервис `python_test` (FastAPI, порт 8100)
**Ключевые модули:**
- `python_test/app/api/routes/rag.py` — эндпоинты `/search`, `/documents`, `/sources`, `/stats`
- `python_test/app/repositories/document_repository.py` — KNN-запросы к pgvector
- `python_test/app/clients/ollama.py` — эмбеддинг запроса
- `python_test/app/services/kb_reader.py` — инвентаризация источников (`/sources`)

## Назначение

Читающая половина RAG: косинусный семантический поиск (KNN) по проиндексированной базе знаний, плюс наблюдательные эндпоинты содержимого индекса. Используется верхним уровнем (LLM-агент/n8n) как инструмент retrieval.

## API контракты

### POST `/search` (scope `rag:read`)
Тело (`SearchRequest`, `extra="forbid"`):

| Поле | Тип | Default | Ограничения | Описание |
|---|---|---|---|---|
| `query` | str | — | 1..8000 симв. | Текст запроса |
| `top_k` | int | 5 | 1..50 | Число возвращаемых совпадений |
| `min_similarity` | float | 0.0 | −1..1 | Порог косинусной близости |

Ответ `200`: `list[SearchHit]` — `document_id: UUID`, `concept_id: str`, `title: str|null`, `category: str|null`, `source_path: str`, `similarity: float`, `payload: dict` (полный исходный JSON концепта).

Алгоритм: `embed("search: " + query)` → SQL KNN `embedding <=> query_vector` (косинусное расстояние), `similarity = 1 − distance`, фильтр `>= min_similarity`, сортировка по расстоянию, `LIMIT top_k`, только строки текущей `model`.

### GET `/documents?limit=100` (scope `rag:read`, limit 1..1000)
Список последних проиндексированных концептов: `list[ConceptPreview]` (`document_id, concept_id, title, category, source_path, has_embedding`); LEFT JOIN с эмбеддингами текущей модели, порядок `indexed_at DESC`.

### GET `/sources` (scope `rag:read`)
Инвентаризация файлов knowledge_base **без обращения к БД**: `[{path, concepts, error}]` (относительный путь, число извлечённых концептов, ошибка чтения если была).

### GET `/stats` (scope `rag:read`)
`{documents: count(kb_documents), embeddings: count(kb_embeddings WHERE model=current), indexes: count(pg_indexes на двух таблицах)}`.

### Health (без авторизации)
`GET /live` — статика; `GET /ready` — проверки `postgres` и `ollama` (статус модели через `/api/tags`), ответ `ok|degraded` c `checks{}`.

## Модель данных

Только чтение: `kb_documents` + `kb_embeddings` (см. документ 01). Запрос идёт к `kb_embeddings` с JOIN на документы; обязательный фильтр `e.model = $current_model` — векторы разных моделей не смешиваются.

## Бизнес-правила

1. Префикс `search: ` для запроса и `doc: ` для документов — единый промпт-формат nomic-embed-text; несоблюдение снижает качество поиска.
2. Порог `min_similarity` применяется в SQL (до LIMIT), поэтому `top_k` — максимум, а не гарантированное число результатов.
3. `payload` возвращается как есть (dict; строковый jsonb приводится к dict на уровне репозитория).
4. `/sources` перечитывает файлы на каждый вызов (нет кэша) — тяжёл на большой базе, предназначен для отладки.
5. Все операции с БД логируются с таймингом (`PostgreSQL >>>/<<<`, длительность, число строк).

## Обработка ошибок

| Ситуация | Реакция |
|---|---|
| Ollama недоступна/ошибка эмбеддинга запроса | retry+backoff → `EmbeddingError` → HTTP 500 (через обработчик AppError — код/сообщение) |
| Размерность ответа ≠ 768 | `EmbeddingError` с деталями `{got, expected}` |
| Пустой индекс | `[]` (не ошибка) |
| Неизвестный/битый файл источника | поле `error` в элементе `/sources` |

## Безопасность

JWT Bearer + scope `rag:read` на всех четырёх эндпоинтах; SQL полностью параметризован (вектор передаётся литералом `[...]` в `$1::vector`, без интерполяции пользовательских строк).

## Паттерны

Repository (весь SQL изолирован), KNN over pgvector (`<=>` оператор косинусного расстояния), Observability-эндпоинты (`/stats`, `/sources`), Circuit Breaker у клиента эмбеддингов (общий с сервисом 01).

## Тесты

Прямого теста `/search` в репозитории нет; контракт покрыт схемами (`app/schemas/api_schemas.py`) и тестами индексации, подготавливающими данные.
