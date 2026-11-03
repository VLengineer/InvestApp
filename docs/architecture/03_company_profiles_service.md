# Сервис 3. Профили компаний (ingest + хранение + поиск)

**Реализация:** микросервис `python_test` (FastAPI, порт 8100), префикс `/company-profiles`
**Ключевые модули:**
- `python_test/app/api/routes/company_profiles.py` — эндпоинты
- `python_test/app/services/company_profiles_service.py` — чтение cp.json, склейка текста, ингест
- `python_test/app/repositories/company_profile_repository.py` — SQL таблицы `company_profiles`
- `python_test/app/db/company_profiles_schema.py` — загрузка DDL из `init_db/03_init_company_profiles.sql`
- `company_profiles/cp.json` — источник (16 профилей Мосбиржи; копия в образ на `/app/company_profiles/cp.json`)
- `scripts/load_company_profiles.py` — CLI-аналог ингеста (документ 08)

## Назначение

Хранение эмбеддингов корпоративных профилей компаний: JSON-профиль → «склеенный» текстовый документ (по приоритету полей) → вектор 768d (Ollama) → upsert в `company_profiles` по ключу `figi`. Даёт CRUD-чтение и векторный поиск похожих компаний; является хранилищем для сервиса анализа новостей (документ 04).

## API контракты

### POST `/company-profiles/ingest` (scope `rag:index`)
Тело **не требуется** — путь к `cp.json` фиксирован (env `COMPANY_PROFILES_JSON`, дефолт `<корень сервиса>/company_profiles/cp.json`).
Ответ `IngestResponse`: `{total: int, inserted: int, updated: int, failed: int}`.
Алгоритм: `ensure_schema()` → для каждого профиля: `build_embed_text()` → `embed(text)` → `exists(figi)` → UPSERT. Синхронная обработка всех профилей внутри одного запроса (без фоновой задачи).

### GET `/company-profiles?limit=100&offset=0` (scope `rag:read`)
`list[dict]` кратких колонок: `id, company_name, ticker, figi, description, business_model, market_position, embedding_model, embedding_dim, created_at, updated_at` (ORDER BY id). limit/offset в роуте без валидации (см. «Риски»).

### GET `/company-profiles/{figi}` (scope `rag:read`)
Полная строка профиля (`SELECT *`, все колонки включая jsonb и `embed_text`; **вектор `embedding` тоже возвращается**), 404 `Profile {figi} not found` если нет.

### POST `/company-profiles/search` (scope `rag:read`)
Тело (`SearchRequest` локальной схемы роутера): `query: str` (обязательно), `limit: int = 5 (1..50)`.
Ответ: `list[{company_name, ticker, figi, description, business_model, similarity}]` — KNN `1 − (embedding <=> $1::vector)`, сортировка по расстоянию, LIMIT. Порог сходства не применяется.

## Модель данных (`init_db/03_init_company_profiles.sql`)

Ключевые колонки `company_profiles`: `figi UNIQUE` (ключ upsert), scalar-тексты (`company_name, ticker, description, business_model, market_position, target_audience, geography, competitors TEXT, regulatory_dependencies, historical_patterns`), jsonb-колонки (`technology_stack, keywords_for_embedding, related_entities, news_triggers, key_products, key_figures, financial_metrics_of_interest, correlation_factors`), векторный блок (`embedding vector(768), embedding_model, embedding_dim, embed_text`), таймстемпы `created_at/updated_at`. Таблица идемпотентно создаётся и через docker-entrypoint-initdb.d, и через `ensure_schema()`, читающий **тот же SQL-файл** (парсер вырезает комментарии и целиком блоки `CREATE FUNCTION ... $$...$$`, разбивая остальное по `;`).

## Бизнес-правила

1. **Приоритет склейки текста** (`build_embed_text`): Компания (name+ticker+figi) → Описание → Бизнес-модель → Ключевые слова → Связанные сущности → Новостные триггеры (positive+negative+neutral) → Ключевые продукты → Ключевые фигуры (имя + должность/тип) → Рыночная позиция → Исторические паттерны → Целевая аудитория → География → Конкуренты → Регуляторные зависимости → Технологический стек → Финансовые метрики → Факторы корреляции. Пустые поля пропускаются; формат строк `Метка: значение\n`.
2. Списки вида `{name, type|position|role}` печатаются как `Имя (тип)` со сбалансированными скобками (защита от прежнего бага `strip("() ")`).
3. `competitors` в схеме — TEXT: список из cp.json склеивается через `, ` (`_as_text`), JSON-дамп запрещён.
4. Остальные list/dict-поля пишутся как `json.dumps(..., ensure_ascii=False)` в jsonb.
5. **Upsert по `figi`**: при конфликте обновляются все поля, `embedding`, `embedding_model/dim`, `embed_text`, `updated_at=now()`. Счётчики: `inserted` (figi отсутствовал) / `updated` (существовал) / `failed` (ошибка эмбеддинга — профиль **не пишется**, цикл продолжается).
6. Текст профиля эмбеддится **без** префикса `doc:` (в отличие от RAG), запрос поиска — с префиксом `search: `.
7. Профиль без `figi` допустим: `exists(None)=False`, но UPSERT с NULL-figi создаёт безключевую дублирующую строку при повторе (UNIQUE на NULL не действует) — см. «Риски».
8. Разрешение пути cp.json многократное (env → Settings → `/app/...` → путь рядом с кодом); относительные пути считаются от корня сервиса, а не CWD; абсолютный «хостовый» путь рехостится относительно корня сервиса.

## Обработка ошибок

| Ситуация | Реакция |
|---|---|
| cp.json отсутствует | HTTP 404 с перечислением испробованных путей и подсказкой пересборки образа |
| Неверная структура cp.json (не list и нет ключей profiles/companies) | ValueError → HTTP 500 (`detail=str(exc)`) |
| Ollama упала на конкретном профиле | `failed += 1`, лог ERROR, остальные продолжаются |
| Прочие исключения ингеста/поиска | лог `logger.exception` + HTTP 500 |
| DDL-файл недоступен в образе | WARNING, `ensure_schema` молча пропускает (таблица уже создана init_db) |

## Безопасность

Запись (`ingest`) — scope `rag:index`; чтение/поиск — `rag:read`; единый JWT проекта. Векторный запрос передаётся литералом в `$n::vector` (параметризовано). `GET /{figi}` возвращает `embedding` и `embed_text` целиком — большая нагрузка на канал и раскрытие внутреннего представления (принято сознательно, помечено как риск).

## Паттерны

Слои routes→services→repositories; DI через контейнер (`container.company_profiles`); единый источник DDL (SQL-файл репозитория парсится приложением); Template Method склейки текста (упорядоченный список `(метка, значение)`).

## Тесты

`python_test/app/tests/test_company_profiles.py` — юнит-тесты `build_embed_text`/`_join_list`/разрешения пути cp.json без БД и Ollama.
