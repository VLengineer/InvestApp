"""Фоновые задачи индексации: in-memory реестр задач (паттерн Repository + Observer-прогресс).

Для одного инстанса сервиса этого достаточно; при горизонтальном масштабировании
реестр меняется на Redis/БД-очередь без правки сервисного слоя (интерфейс TaskStore).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.schemas.api_schemas import TaskStatus

logger = logging.getLogger(__name__)

MAX_ERROR_SAMPLES = 50


class TaskAlreadyRunningError(Exception):
    """Индексация уже выполняется (защита от параллельных тяжёлых задач)."""


@dataclass(slots=True)
class IndexTask:
    task_id: UUID
    options: dict[str, Any]
    requested_by: str
    status: TaskStatus = TaskStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total: int = 0
    processed: int = 0
    embedded: int = 0
    stored_documents: int = 0
    skipped_duplicates: int = 0
    failed: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    _asyncio_task: asyncio.Task | None = field(default=None, repr=False)

    def add_error(self, where: str, exc: Exception) -> None:
        self.failed += 1
        if len(self.errors) < MAX_ERROR_SAMPLES:
            self.errors.append({"where": where, "error": f"{exc.__class__.__name__}: {exc}"})

    def snapshot(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total": self.total,
            "processed": self.processed,
            "embedded": self.embedded,
            "stored_documents": self.stored_documents,
            "skipped_duplicates": self.skipped_duplicates,
            "failed": self.failed,
            "errors": list(self.errors),
        }


class TaskRegistry:
    """Потокобезопасный реестр задач с mutex'ом «одна индексация за раз»."""

    def __init__(self) -> None:
        self._tasks: dict[UUID, IndexTask] = {}
        self._lock = asyncio.Lock()
        self._running_id: UUID | None = None

    async def create(self, options: dict[str, Any], requested_by: str) -> IndexTask:
        async with self._lock:
            if self._running_id is not None and self._tasks[self._running_id].status in (
                TaskStatus.PENDING,
                TaskStatus.RUNNING,
            ):
                raise TaskAlreadyRunningError("Индексация уже выполняется — дождитесь завершения")
            task = IndexTask(task_id=uuid4(), options=options, requested_by=requested_by)
            self._tasks[task.task_id] = task
            self._running_id = task.task_id
            return task

    def get(self, task_id: UUID) -> IndexTask | None:
        return self._tasks.get(task_id)

    def release(self, task_id: UUID) -> None:
        if self._running_id == task_id:
            self._running_id = None

    def list_tasks(self, limit: int = 20) -> list[IndexTask]:
        items = sorted(self._tasks.values(), key=lambda t: t.task_id.hex, reverse=True)
        return items[:limit]

    async def cancel(self, task_id: UUID) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task._asyncio_task is None:
            return False
        task._asyncio_task.cancel()
        return True

    def prune(self, max_tasks: int = 100) -> None:
        if len(self._tasks) <= max_tasks:
            return
        finished = [t for t in self._tasks.values() if t.status in
                    (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED)]
        for task in sorted(finished, key=lambda t: t.finished_at or datetime.min.replace(tzinfo=timezone.utc))[:
                len(self._tasks) - max_tasks]:
            self._tasks.pop(task.task_id, None)

    async def shutdown(self) -> None:
        for task in self._tasks.values():
            if task._asyncio_task and not task._asyncio_task.done():
                task._asyncio_task.cancel()
