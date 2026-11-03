# Сервис 4. Анализ новостей: семантический поиск эмитентов по тексту новости

**Реализация:** микросервис `python_test` (FastAPI, порт 8100)
**Ключевые модули:**
- `python_test/app/services/company_search_service.py` — `CompanySearchService`
- `python_test/app/schemas/news.py` — контракт `NewsSearchRequest / CompanyResult / NewsSearchResponse`
- `python_test/app/repositories/company_profile_repository.py` — метод `search_for_news()`
- `python_test/app/api/deps.py` — провайдер `CompanySearchDep`
- смежные артефакты: `init_db/02_init_market_news_ml.sql` (ML-датасет новостей), отсутствующий в ветке код `news_analyzer`

## Назначение

По тексту новости (заголовок/фрагмент) находит наиболее релевантные компании-эмитенты из таблицы `company_profiles`: эмбеддинг запроса через Ollama → косинусный KNN → пороговая фильтрация → полный профиль в ответе. Это «мост» между новостным потоком (n8n/news_analyzer) и базой корпоративных профилей.

> ⚠️ **Статус публикации:** на текущей ветке HTTP-роутер для этого сервиса **не подключён**: сервис собран в контейнере DI и имеет dependency-провайдер (`CompanySearchDep`), но ни один включённый в `api_router` модуль `app/api/routes/` его не вызывает. Документированный контракт ниже — контракт уровня сервиса (ТЗ п.3.4, путь `POST /news/search-companies`). При подключении роутера достаточно обернуть `search_by_news` эндпоинтом со scope `rag:read`.

## Контракт (уровень сервиса; целевой `POST /news/search-companies`)

Вход `NewsSearchRequest` (`extra="ignore"`):

| Поле | Тип | Default | Ограничения | Описание |
|---|---|---|---|---|
| `news_text` | str | — | min_length=10 | Текст новости для эмбеддинга |
| `top_k` | int | 5 | 1..50 | Сколько ближайших компаний вернуть |
| `min_similarity` | float | 0.5 | 0..1 | Порог косинусной близости |
| `sector_filter` | str\|null | null | — | Подстрока сектора; ILIKE по `embed_text` профиля (колонок `sector` в схеме нет) |

Выход `NewsSearchResponse`:
- `results: list[CompanyResult]` — `company_name, ticker, figi, similarity (round 6), profile{...}` (полный профиль без ключа `company_name`; datetime→ISO, Decimal→float через `_to_jsonable`);
- `query_embedding_dim: int` (768);
- `model: str` (использованная эмбеддинг-модель).

Алгоритм: `embed("search: " + news_text)` → `search_for_news(vector_pg, limit=top_k, sector_filter)` → отсечь `similarity < min_similarity`. SQL берёт `top_k` ближайших **до** порога (порог применяется в Python), т.е. при низком пороге результатов может быть меньше top_k после фильтрации.

## Модель данных

Только чтение `company_profiles` (см. документ 03). `search_for_news` возвращает расширенный набор колонок: `company_name, ticker, figi, description, business_model, market_position, competitors, keywords_for_embedding, related_entities, news_triggers, key_products, key_figures, historical_patterns, embedding_model, embedding_dim, similarity`. Условие `WHERE embedding IS NOT NULL` — профили без вектора не участвуют.

## Бизнес-правила

1. Единый промпт-формат с сервисом поиска профилей: запрос всегда с префиксом `search: `.
2. Фильтр сектора — регистронезависимая подстрока по склеенному тексту профиля (`embed_text ILIKE '%…%'`), а не по структурированному полю.
3. `profile` включает метаданные вектора (`embedding_model`, `embedding_dim`), но не сам вектор и не `id/embed_text` (колонки не запрошены репозиторием).
4. Округление `similarity` до 6 знаков выполняется на уровне сервиса.
5. Пустой результат — нормальное состояние (`results: []`).

## Обработка ошибок

| Ситуация | Реакция |
|---|---|
| Ollama недоступна | retry/backoff клиента → `EmbeddingError` наружу (при подключении роутера — 500 через AppError-handler) |
| `news_text` короче 10 симв. | ValidationError Pydantic (422) — до обращения к модели |
| Профиль без `company_name` в строке БД | KeyError при сборке `CompanyResult` — данные должны быть ингестированы корректно (колонка NOT NULL в схеме) |

## Безопасность

Расчётный scope — `rag:read` (чтение). JWT единый проектный. SQL параметризован, включая `sector_filter` (`$2::text IS NULL OR embed_text ILIKE '%' || $2 || '%'`) — интерполяции нет.

## Паттерны

Facade над Ollama-клиентом и репозиторием; переиспользование инфраструктуры сервиса 03 (тот же `CompanyProfileRepository` и `OllamaEmbeddingClient` из DI-контейнера); адаптация типов БД→JSON на границе presentation (`_to_jsonable`).

## Тесты

Прямых тестов в репозитории нет; логика фильтрации/схем покрыта косвенно тестами сервисов 03 (формат `embed_text`, `vector_to_pg`).
