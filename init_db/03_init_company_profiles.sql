
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS company_profiles (
    id              BIGSERIAL PRIMARY KEY,
    
    -- Идентификаторы инструмента
    company_name    TEXT        NOT NULL,
    ticker          VARCHAR(16) NOT NULL,
    figi            VARCHAR(12) NOT NULL,
    isin            VARCHAR(12),
    sector          TEXT,
    sub_sector      TEXT,
    
    -- Полный профиль (весь JSON целиком, чтобы не терять поля)
    profile         JSONB       NOT NULL,
    
    -- Склеенный текст, который прогоняли через embedding-модель
    embedding_text  TEXT        NOT NULL,
    
    -- Вектор: 1024 для bge-m3, 768 для nomic-embed-text
    embedding       vector(768),
    
    -- Метаданные для версионирования модели
    embedding_model VARCHAR(64) NOT NULL DEFAULT 'bge-m3',
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    CONSTRAINT uq_company_figi UNIQUE (figi)
);

-- Векторный индекс (cosine — стандарт для текстовых эмбеддингов)
CREATE INDEX IF NOT EXISTS idx_company_profiles_embedding
    ON company_profiles
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Индексы для фильтрации по метаданным
CREATE INDEX IF NOT EXISTS idx_company_profiles_ticker ON company_profiles (ticker);
CREATE INDEX IF NOT EXISTS idx_company_profiles_sector ON company_profiles (sector);
CREATE INDEX IF NOT EXISTS idx_company_profiles_jsonb  ON company_profiles USING gin (profile);

-- Автообновление updated_at
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_company_profiles_updated_at ON company_profiles;
CREATE TRIGGER trg_company_profiles_updated_at
    BEFORE UPDATE ON company_profiles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE company_profiles IS 'Профили компаний с эмбеддингами для семантического поиска по новостям';