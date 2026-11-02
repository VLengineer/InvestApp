-- ============================================================
-- Микросервис scheduler_service: состояние планировщика и очередь задач.
-- Выполняется автоматически образом postgres при ПЕРВОМ старте
-- (/docker-entrypoint-initdb.d). Повторно скрипты не запускаются,
-- поэтому всё идемпотентно (IF NOT EXISTS).
-- Дублирует DDL из scheduler_service/app/db/database.py (SCHEMA_DDL) —
-- для локального запуска без docker init.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

-- Singleton-строка: флаг активности планировщика (POST /api/v1/scheduler|/start|/stop).
CREATE TABLE IF NOT EXISTS scheduler_state (
    id        INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

INSERT INTO scheduler_state (id, is_active)
VALUES (1, TRUE)
ON CONFLICT (id) DO NOTHING;

-- Очередь задач воркера: n8n обновляет статус через callback-эндпоинт.
CREATE TABLE IF NOT EXISTS tasks (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    status     VARCHAR(16) NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending', 'completed', 'rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks (status);
CREATE INDEX IF NOT EXISTS ix_tasks_created_at ON tasks (created_at DESC);
