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

-- Диагностические поля для баз, созданных до этой версии (идемпотентная миграция):
-- воркер пишет сюда последние счётчики очереди и текст последнего решения —
-- это видно через GET /api/v1/scheduler/queue даже после рестарта контейнера.
ALTER TABLE scheduler_state ADD COLUMN IF NOT EXISTS waiting_count INT NOT NULL DEFAULT 0;
ALTER TABLE scheduler_state ADD COLUMN IF NOT EXISTS processing_count INT NOT NULL DEFAULT 0;
ALTER TABLE scheduler_state ADD COLUMN IF NOT EXISTS last_worker_message TEXT;
ALTER TABLE scheduler_state ADD COLUMN IF NOT EXISTS last_cycle_at TIMESTAMPTZ;

INSERT INTO scheduler_state (id, is_active)
VALUES (1, TRUE)
ON CONFLICT (id) DO NOTHING;

-- Очередь задач воркера (FIFO): задачи создаются в статусе 'waiting';
-- воркер берёт самую старую waiting и переводит её в 'processing'.
-- Итоговый статус ('completed' | 'error') устанавливает n8n через callback-эндпоинт.
CREATE TABLE IF NOT EXISTS tasks (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    status     VARCHAR(16) NOT NULL DEFAULT 'waiting'
               CHECK (status IN ('waiting', 'processing', 'completed', 'error')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks (status);
CREATE INDEX IF NOT EXISTS ix_tasks_created_at ON tasks (created_at DESC);

-- Миграция для баз, созданных ДО смены модели статусов (идемпотентно):
-- переименование «старых» статусов pending/rejected -> waiting/error.
UPDATE tasks SET status = 'waiting', updated_at = now() WHERE status = 'pending';
UPDATE tasks SET status = 'error',   updated_at = now() WHERE status = 'rejected';
