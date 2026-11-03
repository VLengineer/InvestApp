# Сервис 9. BFF финансового дашборда (`backend-frontend`) + SPA `frontend`

**Реализация:** контейнер `backend-frontend` (FastAPI, порт **8300** в сети `app_net`, наружу — только `127.0.0.1:${MARKET_API_PORT}`) и контейнер `frontend` (Vue 3 + TypeScript SPA, Vite dev-server, порт **5173**).
**Ключевые модули BFF:**
- `backend-frontend/app/main.py` — точка входа: lifespan (`MarketService.start()/stop()` — фоновый polling-цикл рассылки), CORS, единый `api_router`, подключение `ws_router`
- `backend-frontend/app/api/routes/market_data.py` — REST `prefix="/api/market"`: `GET /figis`, `GET /initial-data?figi=…` (последние 500 записей, хронологический порядок, 404 для неизвестного FIGI), `GET /news/{news_id}` (полная запись для модалки)
- `backend-frontend/app/api/routes/health.py` — `GET /live`, `GET /ready` (проверка БД)
- `backend-frontend/app/routers/websocket.py` — WS `/ws/market-updates`: клиент шлёт `{"type":"subscribe","figi":"…"}` (валидация `^[A-Za-z0-9]+$`, 1–32), сервер отвечает `subscribe_ack` и рассылает `{"type":"new_data","data":MarketDataItem,"figi":"…"}`; служебные `unsubscribe`, `ping`, `error`
- `backend-frontend/app/services/market_service.py` — бизнес-логика + фоновый цикл рассылки новых данных подписчикам
- `backend-frontend/app/repositories/market_repository.py` — asyncpg-запросы к `market_news_ml_dataset`; толерантная десериализация `ai_raw_response` (`json.loads` строки из БД → dict, fallback `None`)
- `backend-frontend/app/schemas/market_data.py` — контракты: `MarketDataItem` (свеча OHLCV + объёмы buy/sell, индикаторы `rsi_14/stoch_k/stoch_d/cci_20/williams_r/roc_12/mfi_14/macd/macd_signal/adx_14/atr_14`, стакан/лимиты, новостные поля, `ai_text_summary`, `ai_raw_response: dict | None`), `FigiListResponse`, `InitialDataResponse`, `NewsResponse`
- тесты: `backend-frontend/tests/test_api.py` (9 шт., фейковый asyncpg-пул: REST, валидация FIGI/UUID, WS-подписка и фильтрация по FIGI, polling-рассылка)

**Ключевые модули frontend:**
- `frontend/src/views/Dashboard.vue` — страница дашборда: `initDashboard()` (FIGI → initial-data → WS-подписка на стартовый FIGI), защита от гонок `/figis ↔ /initial-data`, `brokenFigis`, одиночный `watch(selectedFigi)`
- `frontend/src/api/market.ts` — REST-клиент, относительные пути `/api/market/*`
- `frontend/src/composables/useWebSocket.ts` — WS-клиент, URL относительно текущего хоста (`ws(s)://<host>/ws/market-updates`)
- `frontend/src/components/PriceChart.vue` — свечи (Lightweight Charts 4), источник синхронизации времени
- `frontend/src/components/OscillatorCharts.vue` — осцилляторы RSI/MACD/стохастик и др. (ECharts 5): tooltip-crosshair, DataZoom (колесо/пинч/панорамирование), кнопка «На весь экран», синхронизация окна с PriceChart
- `frontend/src/composables/useChartSync.ts` — общий хаб time-scale/crosshair (защита от эха событий); `useFullscreen.ts` — Fullscreen API
- `frontend/src/components/AICard.vue` — карточка ИИ-аналитики: базовые метрики + сворачиваемый блок «Развёрнутый анализ ИИ» из `ai_raw_response` (`src/types/aiAnalysis.ts`: TS-интерфейсы по образцу `temp.json` + tolerant-парсер `parseAiRawAnalysis()`; поддержка написания `ai_raw_responce`)
- `frontend/vite.config.js` — dev-прокси: `/api/*` → `MARKET_API_PROXY_TARGET` (default `http://localhost:8300`), `/ws` → тот же target со `ws:true`

## Назначение

BFF (Backend-for-Frontend) финансового дашборда: единственный читатель таблицы `market_news_ml_dataset` (колонки — свеча + расчётные индикаторы + новостной контекст + сырой JSON-ответ ИИ `ai_raw_response`). Наполнением датасета занимается отсутствующий в ветке `news_analyzer`/n8n-пайплайн — BFF его не пишет. WebSocket обеспечивает near-real-time доставку новых записей (polling БД в фоновом цикле `MarketService`).

## Данные и поток

```
PostgreSQL market_news_ml_dataset ──asyncpg──▶ MarketRepository ─▶ MarketService
   REST: /api/market/figis | initial-data | news/{id}                │ polling-цикл (lifespan)
        ▼                                                            ▼
 Vite dev-proxy (:5173 → :8300) ◀──── Vue SPA Dashboard.vue ──◀ WS /ws/market-updates {new_data}
```

## Особенности безопасности

- JWT-авторизация **не используется**: сервис доступен только из сети `app_net` и с хоста через проброс на `127.0.0.1` (см. README, п. «Общие конвенции»). CORS настроен под dev-сценарий Vite.
- Валидация входа — на уровне Pydantic-схем и регулярных выражений FIGI/UUID; SQL-инъекций нет (параметризованные asyncpg-запросы).

## Известные расхождения / примечания

1. Канон колонки/поля — `ai_raw_response`; историческое написание `ai_raw_responce` встречается в ТЗ и допускается frontend-слоем как fallback.
2. Для локального запуска тестов нужны env `POSTGRES_USER`/`POSTGRES_PASSWORD` (в контейнере приходят из `backend-frontend/.env`).
3. Смена стека осцилляторов: блоки были переведены со статичной отрисовки на интерактивные ECharts-графики с двусторонней синхронизацией zoom/pan/crosshair со свечным графиком (Lightweight Charts) через `useChartSync`.
