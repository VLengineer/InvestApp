-- ============================================================
-- Инициализация БД для микросервиса индексации базы знаний (RAG).
-- Выполняется автоматически образом pgvector/pgvector:pg16 при ПЕРВОМ старте
-- контейнера postgres (каталог /docker-entrypoint-initdb.d).
-- Повторно скрипты не запускаются, поэтому всё идемпотентно (IF NOT EXISTS).
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

-- ------------------------------------------------------------
-- Таблица 1: сами документы (данные из knowledge_base/*.json)
-- Один файл JSON содержит список концептов; каждый концепт = одна строка.
-- content_hash (SHA-256 канонического JSON концепта) — механизм защиты от дублей.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_documents (
    document_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_path   text        NOT NULL,           -- относительный путь файла в knowledge_base
    concept_id    text        NOT NULL,           -- "id" из JSON-концепта
    title         text,
    category      text,
    payload       jsonb       NOT NULL,           -- полный исходный JSON концепта
    content_hash  char(64)    NOT NULL,           -- sha256(payload) — детекция дубликатов
    indexed_at    timestamptz NOT NULL DEFAULT now()
);

-- Глобальная уникальность по содержимому (дубликаты с разным путём тоже отсекаются)
CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_documents_content_hash ON kb_documents (content_hash);
-- Быстрый поиск по логическому id концепта и по файлу-источнику
CREATE INDEX IF NOT EXISTS ix_kb_documents_concept_id ON kb_documents (concept_id);
CREATE INDEX IF NOT EXISTS ix_kb_documents_source_path ON kb_documents (source_path);
-- Полнотекстовый поиск по заголовку (дополнение к векторному)
CREATE INDEX IF NOT EXISTS ix_kb_documents_title_fts ON kb_documents USING gin (to_tsvector('russian', coalesce(title, '')));

-- ------------------------------------------------------------
-- Таблица 2: векторы эмбеддингов, привязанные к uuid документа
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_embeddings (
    embedding_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id   uuid NOT NULL REFERENCES kb_documents (document_id) ON DELETE CASCADE,
    chunk_index   int  NOT NULL DEFAULT 0,        -- пока 1 чанк на документ
    model         text NOT NULL,                  -- например 'embeddinggemma-2'
    embedding     vector(768) NOT NULL,           -- размерность проверяется сервисом при старте
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index, model)
);

-- Векторный KNN-индекс (cosine — стандарт для нормализованных эмбеддингов)
CREATE INDEX IF NOT EXISTS ix_kb_embeddings_vector_hnsw
    ON kb_embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS ix_kb_embeddings_document_id
    ON kb_embeddings (document_id);

-- ------------------------------------------------------------
-- Представление для семантического поиска (JOIN двух таблиц)
-- Пример: SELECT ..., embedding <=> :query_vec AS distance
--          FROM kb_documents_with_embedding ORDER BY embedding <=> :query_vec LIMIT 10;
-- ------------------------------------------------------------
CREATE OR REPLACE VIEW kb_documents_with_embedding AS
SELECT d.document_id, d.source_path, d.concept_id, d.title, d.category,
       d.payload, e.model, e.embedding
FROM kb_documents d
JOIN kb_embeddings e ON e.document_id = d.document_id;
