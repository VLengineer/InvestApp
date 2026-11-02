-- 03_init_company_profiles.sql
-- Инициализация таблицы company_profiles (PostgreSQL + pgvector)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS company_profiles (
    id                          BIGSERIAL PRIMARY KEY,
    -- Идентификация компании
    company_name                TEXT NOT NULL,
    ticker                      TEXT,
    figi                        TEXT UNIQUE,
    -- Основные смысловые поля профиля
    description                 TEXT,
    business_model              TEXT,
    market_position             TEXT,
    target_audience             TEXT,
    geography                   TEXT,
    competitors                 TEXT,
    regulatory_dependencies     TEXT,
    technology_stack            TEXT,
    historical_patterns         TEXT,
    -- JSONB-поля
    keywords_for_embedding      JSONB,            -- ["слово", ...]
    related_entities            JSONB,            -- [{"name","type"}, ...]
    news_triggers               JSONB,            -- {"positive": [...], "negative": [...], "neutral": [...]}
    key_products                JSONB,            -- ["продукт", ...]
    key_figures                 JSONB,            -- [{"name","position"}, ...]
    financial_metrics_of_interest JSONB,          -- ["Показатель", ...]
    correlation_factors         JSONB,            -- ["Фактор", ...]
    -- Векторное представление склеенного текста профиля
    embedding                   VECTOR(768),
    embedding_model             TEXT,
    embedding_dim               INT,
    -- Служебное поле со всем склеенным текстом (для отладка/повторной генерации)
    embed_text                  TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_company_profiles_embedding
    ON company_profiles USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_company_profiles_ticker
    ON company_profiles (ticker);
