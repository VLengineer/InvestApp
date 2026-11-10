"""DDL схемы и SQL запросы."""

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS robot_market_data (
    timestamp         TIMESTAMPTZ      NOT NULL,
    figi              VARCHAR(32)      NOT NULL,
    candle_open       DOUBLE PRECISION,
    candle_high       DOUBLE PRECISION,
    candle_low        DOUBLE PRECISION,
    candle_close      DOUBLE PRECISION,
    candle_volume     BIGINT,
    candle_is_complete BOOLEAN,

    -- Legacy columns (TYPE_OF_PRICE_CLOSE, backward compatibility)
    bb_upper          DOUBLE PRECISION,
    bb_middle         DOUBLE PRECISION,
    bb_lower          DOUBLE PRECISION,
    ema_signal        DOUBLE PRECISION,
    sma_signal        DOUBLE PRECISION,
    rsi_signal        DOUBLE PRECISION,
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
CREATE INDEX IF NOT EXISTS ix_robot_market_data_timestamp
    ON robot_market_data (timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_robot_market_data_figi
    ON robot_market_data (figi);
"""

# Колонки в порядке, соответствующем $N плейсхолдерам
INSERT_COLUMNS = [
    "timestamp", "figi",
    "candle_open", "candle_high", "candle_low", "candle_close",
    "candle_volume", "candle_is_complete",
    # legacy (close without prefix)
    "bb_upper", "bb_middle", "bb_lower",
    "ema_signal", "sma_signal", "rsi_signal",
    "macd_value", "macd_signal",
    # close
    "close_bb_upper", "close_bb_middle", "close_bb_lower",
    "close_ema_signal", "close_rsi_signal", "close_sma_signal",
    "close_macd_value", "close_macd_signal",
    # open
    "open_bb_upper", "open_bb_middle", "open_bb_lower",
    "open_ema_signal", "open_rsi_signal", "open_sma_signal",
    "open_macd_value", "open_macd_signal",
    # high
    "high_bb_upper", "high_bb_middle", "high_bb_lower",
    "high_ema_signal", "high_rsi_signal", "high_sma_signal",
    "high_macd_value", "high_macd_signal",
    # low
    "low_bb_upper", "low_bb_middle", "low_bb_lower",
    "low_ema_signal", "low_rsi_signal", "low_sma_signal",
    "low_macd_value", "low_macd_signal",
    # avg
    "avg_bb_upper", "avg_bb_middle", "avg_bb_lower",
    "avg_ema_signal", "avg_rsi_signal", "avg_sma_signal",
    "avg_macd_value", "avg_macd_signal",
]

_placeholders = ", ".join(f"${i}" for i in range(1, len(INSERT_COLUMNS) + 1))
_columns_str = ", ".join(INSERT_COLUMNS)

INSERT_SQL = f"""
INSERT INTO robot_market_data (
    {_columns_str}
) VALUES (
    {_placeholders}
)
ON CONFLICT (timestamp, figi) DO NOTHING
"""
