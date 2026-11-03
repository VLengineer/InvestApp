-- ============================================================
-- Микросервис news_analyzer: ML-датасет рыночных новостей.
-- Выполняется автоматически образом postgres при ПЕРВОМ старте
-- (/docker-entrypoint-initdb.d). Повторно скрипты не запускаются,
-- поэтому всё идемпотентно (IF NOT EXISTS).
-- Дублирует DDL из python_test/news_analyzer/repository.py
-- (ensure_schema) — для локального запуска без docker init.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

CREATE TABLE IF NOT EXISTS market_news_ml_dataset (
    -- 1. Базовые поля (источник и новость).
    -- figi — идентификатор инструмента Tinkoff Invest API (переименовано из ticker).
    -- source/title/content/ts — nullable: строка может создаваться только с рыночными
    -- данными (без привязанной новости), n8n заполняет колонки напрямую.
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    figi VARCHAR(32),
    source VARCHAR(255),
    title TEXT,
    content TEXT,
    -- Время публикации новости (TIMESTAMP(9) WITH TIME ZONE — наносекунды)
    ts TIMESTAMP(9) WITH TIME ZONE,

    -- 2. Данные свечи (OHLCV) на момент публикации новости
    -- Время начала свечи (отдельно от ts, т.к. ts — это время самой новости)
    candle_time TIMESTAMP(9) WITH TIME ZONE,
    -- Числовые поля-индикаторы от провайдера фондовых рынков — строгий NOT NULL
    -- (запись не существует без цены/объёма; цены float64 — удобно для ML)
    open_price  DOUBLE PRECISION NOT NULL,
    high_price  DOUBLE PRECISION NOT NULL,
    low_price   DOUBLE PRECISION NOT NULL,
    close_price DOUBLE PRECISION NOT NULL,
    -- Объёмы
    volume      BIGINT NOT NULL,      -- суммарный объём свечи
    volume_buy  BIGINT NOT NULL,      -- объём покупок
    volume_sell BIGINT NOT NULL,      -- объём продаж
    -- Флаг завершённости свечи (isComplete)
    is_complete BOOLEAN,

    -- 3. Технические индикаторы (числовые поля от провайдера — NOT NULL)
    -- Осцилляторы (импульс / перекупленность-перепроданность)
    rsi_14 DOUBLE PRECISION NOT NULL,          -- RSI (Relative Strength Index)
    stoch_k DOUBLE PRECISION NOT NULL,         -- Stochastic Oscillator (%K)
    stoch_d DOUBLE PRECISION NOT NULL,         -- Stochastic Oscillator (%D)
    cci_20 DOUBLE PRECISION NOT NULL,          -- CCI (Commodity Channel Index)
    williams_r DOUBLE PRECISION NOT NULL,      -- Williams %R
    roc_12 DOUBLE PRECISION NOT NULL,          -- ROC (Rate of Change)
    mfi_14 DOUBLE PRECISION NOT NULL,          -- MFI (Money Flow Index) — объёмно-взвешенный RSI

    -- Тренд и волатильность
    macd DOUBLE PRECISION NOT NULL,            -- MACD
    macd_signal DOUBLE PRECISION NOT NULL,     -- MACD Signal line
    adx_14 DOUBLE PRECISION NOT NULL,          -- ADX (Average Directional Index) — сила тренда
    atr_14 DOUBLE PRECISION NOT NULL,          -- ATR (Average True Range) — волатильность

    -- 3b. Рыночные данные Tinkoff Invest API (n8n получает их от провайдера
    -- и заносит напрямую в БД). Структура MoneyValue = {units, nano, currency}.
    limit_up_units   DOUBLE PRECISION NOT NULL,   -- UpperPrice (лимит вверх)
    limit_down_units DOUBLE PRECISION NOT NULL,   -- LowerPrice (лимит вниз)
    close_price_units DOUBLE PRECISION NOT NULL,  -- ClosePrice (закрытие, MoneyValue.units)
    last_price_units  DOUBLE PRECISION NOT NULL,  -- LastPrice (последняя цена, MoneyValue.units)
    price_currency VARCHAR(16) NOT NULL,          -- валюта цены (RUB/USD/CNY...)

    -- Временные метки ответов провайдера
    last_price_ts  TIMESTAMP(9) WITH TIME ZONE,   -- время получения LastPrice
    orderbook_ts   TIMESTAMP(9) WITH TIME ZONE,   -- время снапшота стакана
    close_price_ts TIMESTAMP(9) WITH TIME ZONE,   -- время ClosePrice

    -- Глубина стаканa (OrderBookRequest.depth); сами заявки — в tables
    -- orderbook_asks / orderbook_bids (могут быть пустыми — FK, nullable)
    depth INTEGER,

    -- 4. Числовая аналитика от ИИ (Фичи для ML)
    ai_sentiment_score DOUBLE PRECISION,  -- Тональность: от -1.0 (негатив) до 1.0 (позитив)
    ai_relevance_score DOUBLE PRECISION,  -- Релевантность: от 0.0 до 1.0
    ai_expected_impact DOUBLE PRECISION,  -- Ожидаемое влияние ИИ: прогноз движения в % или лог. доходности
    ai_confidence DOUBLE PRECISION,       -- Уверенность ИИ: от 0.0 до 1.0

    -- 5. Текстовая аналитика от ИИ
    ai_text_summary TEXT,                 -- Краткое резюме новости от LLM
    ai_raw_response JSONB,                -- Сырой JSON ответ от Ollama

    -- 6. Целевые переменные (Target) для обучения классификации
    target_horizon_minutes INT NOT NULL DEFAULT 60,   -- Горизонт предсказания
    target_future_return_pct DOUBLE PRECISION,        -- Фактическое изменение цены в %
    target_direction SMALLINT,                        -- 1 = рост, 0 = боковик, -1 = падение
    target_volatility_threshold_pct DOUBLE PRECISION  -- Порог волатильности (в %)
);

-- Индексы для быстрой выборки датасета по времени
CREATE INDEX IF NOT EXISTS idx_ml_dataset_ts          ON market_news_ml_dataset (ts DESC);
CREATE INDEX IF NOT EXISTS idx_ml_dataset_candle_time ON market_news_ml_dataset (candle_time DESC);
CREATE INDEX IF NOT EXISTS idx_ml_dataset_figi        ON market_news_ml_dataset (figi);

-- ============================================================
-- Стакан (глубина рынка) Tinkoff Invest API: заявки продавцов (asks)
-- и покупателей (bids). Отдельные таблицы, потому что массивы могут
-- быть пустыми — отсутствие строк = пустой стакан (nullable по смыслу).
-- Price = MoneyValue {units, nano}; quantity = Quantity {value}.
-- ============================================================

CREATE TABLE IF NOT EXISTS orderbook_asks (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market_data_id UUID NOT NULL REFERENCES market_news_ml_dataset (id) ON DELETE CASCADE,
    position       INTEGER NOT NULL,               -- позиция в стакане (1, 2, 3...)
    price_units    BIGINT NOT NULL,                -- Price.units (целая часть)
    price_nano     INTEGER NOT NULL,               -- Price.nano (доли, знак у units)
    quantity       NUMERIC(20,9) NOT NULL,         -- Quantity.value (лоты/штуки)
    CONSTRAINT uq_orderbook_asks_pos UNIQUE (market_data_id, position)
);

CREATE TABLE IF NOT EXISTS orderbook_bids (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market_data_id UUID NOT NULL REFERENCES market_news_ml_dataset (id) ON DELETE CASCADE,
    position       INTEGER NOT NULL,               -- позиция в стакане (1, 2, 3...)
    price_units    BIGINT NOT NULL,                -- Price.units (целая часть)
    price_nano     INTEGER NOT NULL,               -- Price.nano (доли, знак у units)
    quantity       NUMERIC(20,9) NOT NULL,         -- Quantity.value (лоты/штуки)
    CONSTRAINT uq_orderbook_bids_pos UNIQUE (market_data_id, position)
);

-- Выборка стакана по записи датасета (упорядоченная по глубине)
CREATE INDEX IF NOT EXISTS idx_orderbook_asks_market ON orderbook_asks (market_data_id, position);
CREATE INDEX IF NOT EXISTS idx_orderbook_bids_market ON orderbook_bids (market_data_id, position);