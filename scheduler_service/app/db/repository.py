"""Репозиторий scheduler_service: таблицы ``scheduler_state`` и ``tasks``.

Весь доступ к БД — только через asyncpg-пул (строго асинхронно, без блокировок).
Паттерн как в python_test/app/news_analyzer/repository.py: тонкая обёртка над
живым пулом, SQL-константы сверху модуля.

Модель очереди задач (FIFO, 4 статуса):
    waiting -> processing (воркер) -> completed | error (ставит n8n через callback).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)

# ------------------------------- scheduler_state ------------------------------
_GET_STATE_SQL = "SELECT is_active FROM scheduler_state WHERE id = 1"
_SET_STATE_SQL = """
    INSERT INTO scheduler_state (id, is_active)
    VALUES (1, $1)
    ON CONFLICT (id) DO UPDATE SET is_active = EXCLUDED.is_active
"""

# ----------------------------------- tasks ------------------------------------
# Новая задача всегда создаётся в статусе 'waiting' — независимо от того,
# чем закончилась предыдущая (очередь FIFO).
_INSERT_TASK_SQL = """
    INSERT INTO tasks (id, status)
    VALUES ($1, 'waiting')
    RETURNING id, status, created_at
"""
_GET_TASK_STATUS_SQL = "SELECT status FROM tasks WHERE id = $1"
_UPDATE_TASK_STATUS_SQL = """
    UPDATE tasks
    SET status = $2, updated_at = now()
    WHERE id = $1
    RETURNING id, status, updated_at
"""
# a) Есть ли прямо сейчас задача в работе? (одна одновременная обработка)
_GET_PROCESSING_TASK_SQL = """
    SELECT id, created_at FROM tasks
    WHERE status = 'processing'
    ORDER BY created_at ASC
    LIMIT 1
"""
# b) Самая старая waiting-задача (FIFO: ORDER BY created_at ASC LIMIT 1)
_GET_OLDEST_WAITING_TASK_SQL = """
    SELECT id FROM tasks
    WHERE status = 'waiting'
    ORDER BY created_at ASC
    LIMIT 1
"""
# c) Атомарный захват waiting -> processing (исключает гонку при репликации воркера).
_CLAIM_TASK_SQL = """
    UPDATE tasks
    SET status = 'processing', updated_at = now()
    WHERE id = $1 AND status = 'waiting'
    RETURNING id, status, updated_at
"""


class SchedulerRepository:
    """CRUD для состояния планировщика и очереди задач."""

    def __init__(self, pool_provider: Any) -> None:
        # pool_provider — объект с атрибутом .pool (app.db.database.Database):
        # ссылка на пул берётся в момент вызова, а не при сборке контейнера.
        self._pool_provider = pool_provider

    @property
    def _pool(self) -> asyncpg.Pool:
        return self._pool_provider.pool  # type: ignore[union-attr,no-any-return]

    # ----------------------------- scheduler_state ----------------------------
    async def get_is_active(self) -> bool:
        """Текущий флаг планировщика; если строки нет (голая БД) — считаем активной."""
        row = await self._pool.fetchrow(_GET_STATE_SQL)
        return bool(row["is_active"]) if row else True

    async def set_is_active(self, is_active: bool) -> bool:
        await self._pool.execute(_SET_STATE_SQL, is_active)
        return is_active

    # ---------------------------------- tasks ---------------------------------
    async def create_task(self, task_id: UUID) -> dict[str, Any]:
        """Создаёт задачу со статусом 'waiting' (uuid — ключ идемпотентности callback)."""
        row = await self._pool.fetchrow(_INSERT_TASK_SQL, task_id)
        return {"id": row["id"], "status": row["status"], "created_at": row["created_at"]}

    async def get_task_status(self, task_id: UUID) -> str | None:
        """Статус задачи по uuid или None, если задачи нет."""
        row = await self._pool.fetchrow(_GET_TASK_STATUS_SQL, task_id)
        return str(row["status"]) if row else None

    async def update_task_status(self, task_id: UUID, status: str) -> dict[str, Any] | None:
        """Обновляет статус задачи (callback от n8n); None — если task_id неизвестен."""
        row = await self._pool.fetchrow(_UPDATE_TASK_STATUS_SQL, task_id, status)
        if row is None:
            return None
        return {"id": row["id"], "status": row["status"], "updated_at": row["updated_at"]}

    async def get_processing_task(self) -> dict[str, Any] | None:
        """Текущая задача в статусе 'processing' (или None — в работе пусто).

        Возвращаем id + created_at: по created_at воркер считает страховочный
        таймаут для чужих/перезапущенных задач.
        """
        row = await self._pool.fetchrow(_GET_PROCESSING_TASK_SQL)
        if row is None:
            return None
        return {"id": row["id"], "created_at": row["created_at"]}

    async def get_next_waiting_task(self) -> UUID | None:
        """Самая старая waiting-задача (FIFO), или None — очередь пуста."""
        row = await self._pool.fetchrow(_GET_OLDEST_WAITING_TASK_SQL)
        return row["id"] if row else None

    async def claim_task(self, task_id: UUID) -> dict[str, Any] | None:
        """Переводит waiting-задачу в 'processing'; None — если её уже забрали."""
        row = await self._pool.fetchrow(_CLAIM_TASK_SQL, task_id)
        if row is None:
            return None
        return {"id": row["id"], "status": row["status"], "updated_at": row["updated_at"]}

    async def mark_stale_processing_error(self, timeout_s: int) -> int:
        """Санация «зависших» processing-задач старше timeout_s -> error.

        Страховка после падения контейнера/n8n: callback так и не пришёл —
        задача помечается error, очередь освобождается для следующих задач.
        """
        result = await self._pool.execute(
            """
            UPDATE tasks
            SET status = 'error', updated_at = now()
            WHERE status = 'processing' AND updated_at < now() - make_interval(secs => $1)
            """,
            timeout_s,
        )
        # result вида 'UPDATE N'
        count = int(result.split()[-1])
        if count:
            logger.warning("Санация: %d зависших processing-задач помечены error", count)
        return count
