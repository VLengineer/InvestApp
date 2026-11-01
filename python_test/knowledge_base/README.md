# Сборщик базы знаний — `build_kb.py`

## Почему он нужен
Приложение (`app/services/kb_reader.py`) по умолчанию индексирует **только** файлы,
лежащие в папках с именем **«Общий json»**. В репозитории таких папок 3 (по одной на
раздел), остальные ~390 `.json` лежат в подпапках вида `№7. Правила/...`, `№1. Основные
многофакторные стратегии/...` и в индексацию **не попадали** — отсюда «индексация вернула
202, а таблицы пустые / файлов в плане 3 вместо сотен».

Скрипт обходит **все** подпапки `knowledge_base`, проверяет структуру объектов и собирает
всё в один файл `kb_all.json`.

## Запуск
```bash
cd python_test/knowledge_base

python3 build_kb.py --check                 # только проверка структуры, ничего не пишет
python3 build_kb.py                          # -> kb_all.json + kb_all_report.json
python3 build_kb.py --fix-control-chars      # автопочинка недопустимых \n/\t/" внутри строк JSON
python3 build_kb.py --strict                 # битые JSON => код возврата 1 (для CI)
```

Флаги: `--root PATH`, `--output FILE`, `--require-fields id,title`,
`--allow-dup-ids` (не отбрасывать концепты с повторяющимся `id`), `--strict-schema`
(печатать замечания и про отсутствующие рекомендуемые поля).

## Что умеет
- рекурсивный обход всей базы знаний, любой вложенности (`dict`/`list`);
- концепт = словарь, у которого есть `id` + `title`;
- проверка обязательных (`id`, `title`) и рекомендуемых полей схемы
  (`category`, `essence`, `formula`, `interpretation`, `sector_specifics`,
  `limitations`, `related_concepts`, `search_keywords`, `source_text_excerpt`);
- дедупликация по canonical SHA-256 содержимого + по `id` (первое вхождение выигрывает);
- отчёт `kb_all_report.json`: битые файлы с строкой/колонкой ошибки, файлы без концептов,
  число дублей, разбивка по разделам;
- в каждый объект добавляется `_source` (относительный путь исходного файла).

## Результаты прогона по текущей базе знаний
```
файлов просканировано: 390 (рекурсивно, без kb_all*)
OK:                  386 | битый JSON: 4 | без концептов: 0
концептов найдено:   6556 -> уникальных собрано: 4430
отфильтровано:       1974 дубля содержимого, 152 дубля id
```
Битые файлы (требуют ручной починки — `--fix-control-chars` спасает только «сырые»
управляющие символы, см. ниже):
1. `4. Индикаторы Билла Вильямса/№7. Правила/Rules for using the Bill Williams system.json`
   — Invalid control character (line 75) — **чинится флагом `--fix-control-chars`**;
2. `.../№1. Классические осцилляторы/TRIX.json` — Invalid control character (line 113) —
   **чинится `--fix-control-chars`**;
3. `.../№2. .../AO Histogram Smoothed.json` — Expecting ',' delimiter (line 76) — скорее
   всего пропущена запятая между полями, править вручную;
4. `.../№4. .../AO-AC Momentum Sniper.json` — Unterminated string (line 148) — незакрытая
   кавычка, править вручную.

После `--fix-control-chars`: OK=387, концептов найдено=6565, уникальных=4439.

## Как потом индексировать собранный файл
Вариант А (рекомендуемый, один файл вместо 390):
```bash
mkdir -p merged && python3 build_kb.py --fix-control-chars --output merged/kb_all.json
# в .env контейнера:
KB_ROOT=/app/knowledge_base          # или отдельная папка монтирования
COMMON_DIR_NAMES=merged              # берётся только merged/kb_all.json
```
Вариант Б — индексировать все *.json как есть:
```
COMMON_DIR_NAMES=                    # пустой список = все *.json рекурсивно
```
(если фильтр задан, но ни одного файла под него не попало, приложение теперь само
пишет WARNING и fallback'ом берёт все *.json — пустая индексация больше не «молчит»).

Затем обычным порядком: `POST /index {"limit_documents": 5}` и смотреть
`docker logs -f python_test` — каждый этап (Ollama запрос → ответ → INSERT → document_id)
логируется; итог в БД виден в `GET /stats` и DBeaver (`kb_documents`, `kb_embeddings`).
