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
    -- 1. Базовые поля (источник и новость)
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker VARCHAR(16),
    source VARCHAR(255) NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    -- Время публикации новости (TIMESTAMP(9) WITH TIME ZONE — наносекунды)
    ts TIMESTAMP(9) WITH TIME ZONE NOT NULL,

    -- 2. Данные свечи (OHLCV) на момент публикации новости
    -- Время начала свечи (отдельно от ts, т.к. ts — это время самой новости)
    candle_time TIMESTAMP(9) WITH TIME ZONE,
    -- Цены (float64 — удобно для ML; если нужна точность до долей — замени на NUMERIC(20,9))
    open_price  DOUBLE PRECISION,
    high_price  DOUBLE PRECISION,
    low_price   DOUBLE PRECISION,
    close_price DOUBLE PRECISION,
    -- Объёмы
    volume      BIGINT,             -- суммарный объём свечи
    volume_buy  BIGINT,             -- объём покупок
    volume_sell BIGINT,             -- объём продаж
    -- Флаг завершённости свечи (isComplete)
    is_complete BOOLEAN,

    -- 3. Технические индикаторы
    -- Осцилляторы (импульс / перекупленность-перепроданность)
    rsi_14 DOUBLE PRECISION,          -- RSI (Relative Strength Index)
    stoch_k DOUBLE PRECISION,         -- Stochastic Oscillator (%K)
    stoch_d DOUBLE PRECISION,         -- Stochastic Oscillator (%D)
    cci_20 DOUBLE PRECISION,          -- CCI (Commodity Channel Index)
    williams_r DOUBLE PRECISION,      -- Williams %R
    roc_12 DOUBLE PRECISION,          -- ROC (Rate of Change)
    mfi_14 DOUBLE PRECISION,          -- MFI (Money Flow Index) — объёмно-взвешенный RSI

    -- Тренд и волатильность
    macd DOUBLE PRECISION,            -- MACD
    macd_signal DOUBLE PRECISION,     -- MACD Signal line
    adx_14 DOUBLE PRECISION,          -- ADX (Average Directional Index) — сила тренда
    atr_14 DOUBLE PRECISION,          -- ATR (Average True Range) — волатильность

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
CREATE INDEX IF NOT EXISTS idx_ml_dataset_ticker      ON market_news_ml_dataset (ticker);