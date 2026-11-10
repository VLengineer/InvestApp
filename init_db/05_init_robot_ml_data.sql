-- ============================================================
-- Микросервис robot: таблица для хранения рыночных данных и
-- технических индикаторов (ML-датасет).
-- Выполняется автоматически образом postgres при ПЕРВОМ старте
-- (/docker-entrypoint-initdb.d). Всё идемпотентно (IF NOT EXISTS).
-- Дублирует DDL из robot/main.py (ensure_schema) — для standalone
-- запуска без docker init.
-- ============================================================

-- Снимок рыночных данных + технические индикаторы по 5-минутным свечам.
-- Первичный ключ — составной (timestamp, figi), т.к. один и тот же
-- момент времени может относиться к разным инструментам.
CREATE TABLE IF NOT EXISTS robot_market_data (
    timestamp         TIMESTAMPTZ      NOT NULL,
    figi              VARCHAR(32)      NOT NULL,

    -- Свеча
    candle_open       DOUBLE PRECISION,
    candle_high       DOUBLE PRECISION,
    candle_low        DOUBLE PRECISION,
    candle_close      DOUBLE PRECISION,
    candle_volume     BIGINT,
    candle_is_complete BOOLEAN,

    -- Legacy columns (TYPE_OF_PRICE_CLOSE, backward compatibility)
    -- Bollinger Bands
    bb_upper          DOUBLE PRECISION,
    bb_middle         DOUBLE PRECISION,
    bb_lower          DOUBLE PRECISION,

    -- Сигналы индикаторов
    ema_signal        DOUBLE PRECISION,
    sma_signal        DOUBLE PRECISION,
    rsi_signal        DOUBLE PRECISION,

    -- MACD
    macd_value        DOUBLE PRECISION,
    macd_signal       DOUBLE PRECISION,

    -- TYPE_OF_PRICE_CLOSE
    close_bb_upper    DOUBLE PRECISION,
    close_bb_middle   DOUBLE PRECISION,
    close_bb_lower    DOUBLE PRECISION,
    close_ema_signal  DOUBLE PRECISION,
    close_rsi_signal  DOUBLE PRECISION,
    close_sma_signal  DOUBLE PRECISION,
    close_macd_value  DOUBLE PRECISION,
    close_macd_signal DOUBLE PRECISION,

    -- TYPE_OF_PRICE_OPEN
    open_bb_upper     DOUBLE PRECISION,
    open_bb_middle    DOUBLE PRECISION,
    open_bb_lower     DOUBLE PRECISION,
    open_ema_signal   DOUBLE PRECISION,
    open_rsi_signal   DOUBLE PRECISION,
    open_sma_signal   DOUBLE PRECISION,
    open_macd_value   DOUBLE PRECISION,
    open_macd_signal  DOUBLE PRECISION,

    -- TYPE_OF_PRICE_HIGH
    high_bb_upper     DOUBLE PRECISION,
    high_bb_middle    DOUBLE PRECISION,
    high_bb_lower     DOUBLE PRECISION,
    high_ema_signal   DOUBLE PRECISION,
    high_rsi_signal   DOUBLE PRECISION,
    high_sma_signal   DOUBLE PRECISION,
    high_macd_value   DOUBLE PRECISION,
    high_macd_signal  DOUBLE PRECISION,

    -- TYPE_OF_PRICE_LOW
    low_bb_upper      DOUBLE PRECISION,
    low_bb_middle     DOUBLE PRECISION,
    low_bb_lower      DOUBLE PRECISION,
    low_ema_signal    DOUBLE PRECISION,
    low_rsi_signal    DOUBLE PRECISION,
    low_sma_signal    DOUBLE PRECISION,
    low_macd_value    DOUBLE PRECISION,
    low_macd_signal   DOUBLE PRECISION,

    -- TYPE_OF_PRICE_AVG
    avg_bb_upper      DOUBLE PRECISION,
    avg_bb_middle     DOUBLE PRECISION,
    avg_bb_lower      DOUBLE PRECISION,
    avg_ema_signal    DOUBLE PRECISION,
    avg_rsi_signal    DOUBLE PRECISION,
    avg_sma_signal    DOUBLE PRECISION,
    avg_macd_value    DOUBLE PRECISION,
    avg_macd_signal   DOUBLE PRECISION,

    PRIMARY KEY (timestamp, figi)
);

-- Индексы для типичных запросов: по времени и по инструменту.
CREATE INDEX IF NOT EXISTS ix_robot_market_data_timestamp
    ON robot_market_data (timestamp DESC);

CREATE INDEX IF NOT EXISTS ix_robot_market_data_figi
    ON robot_market_data (figi);
