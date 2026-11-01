-- ============================================================
-- Микросервис news_analyzer: ML-датасет рыночных новостей.
-- Таблицу заполняет сценарий n8n (вебхук news_analizer) — сам python_test
-- в БД не пишет, он только пересылает новость на вебхук n8n.
-- Выполняется автоматически образом postgres при ПЕРВОМ старте
-- (/docker-entrypoint-initdb.d). Повторно скрипты не запускаются,
-- поэтому всё идемпотентно (IF NOT EXISTS).
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

CREATE TABLE IF NOT EXISTS market_news_ml_dataset (
    -- 1. Базовые поля (источник и новость)
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source VARCHAR(255) NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    -- Используем TIMESTAMP(9) WITH TIME ZONE, чтобы сохранить наносекунды
    ts TIMESTAMP(9) WITH TIME ZONE NOT NULL,

    -- 2. Технические индикаторы (Осцилляторы и метрики волатильности)
    -- Используем DOUBLE PRECISION (float8), так как ML-библиотеки работают с float64
    rsi_14 DOUBLE PRECISION,          -- RSI (Relative Strength Index) - импульс
    stoch_k DOUBLE PRECISION,         -- Stochastic Oscillator (%K) - перекупленность/перепроданность
    stoch_d DOUBLE PRECISION,         -- Stochastic Oscillator (%D) - сглаженное значение
    macd DOUBLE PRECISION,            -- MACD - тренд и импульс
    macd_signal DOUBLE PRECISION,     -- MACD Signal line
    atr_14 DOUBLE PRECISION,          -- ATR (Average True Range) - волатильность (критично для новостей!)

    -- 3. Числовая аналитика от ИИ (Фичи для ML)
    ai_sentiment_score DOUBLE PRECISION,  -- Тональность: от -1.0 (негатив) до 1.0 (позитив)
    ai_relevance_score DOUBLE PRECISION,  -- Релевантность: от 0.0 до 1.0 (насколько новость вообще про наш актив)
    ai_expected_impact DOUBLE PRECISION,  -- Ожидаемое влияние ИИ: прогноз движения в % или лог. доходности
    ai_confidence DOUBLE PRECISION,       -- Уверенность ИИ: от 0.0 до 1.0 (можно использовать как вес для loss-функции)

    -- 4. Текстовая аналитика от ИИ
    ai_text_summary TEXT,                 -- Краткое резюме новости от LLM
    ai_raw_response JSONB,                -- Сырой JSON ответ от Ollama (для дебага и парсинга, если формат меняется)

    -- 5. Целевые переменные (Target) для обучения классификации
    target_horizon_minutes INT NOT NULL DEFAULT 60,   -- Горизонт предсказания (напр., 60 мин, 4 часа, 1 день)

    -- Фактическое изменение цены в % за этот период (хранится для гибкости)
    -- Положительное = рост, отрицательное = падение
    target_future_return_pct DOUBLE PRECISION,

    -- Итоговый класс для ML-модели (то, что мы предсказываем)
    --  1 = вырастет (значимый рост)
    --  0 = боковик / шум (изменение в пределах порога)
    -- -1 = упадет (значимое падение)
    target_direction SMALLINT,

    -- Порог волатильности (в %), использованный для определения target_direction
    -- Полезно знать, был ли это просто шум или пробой
    target_volatility_threshold_pct DOUBLE PRECISION
);

-- Индексы для быстрой выборки датасета по времени
CREATE INDEX IF NOT EXISTS idx_ml_dataset_ts ON market_news_ml_dataset (ts DESC);
