"""Pydantic v2-схемы API-контракта scheduler_service (presentation-слой)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TaskStatus(StrEnum):
    """Статусы задачи в очереди (совпадают с CHECK-ограничением в БД).

    waiting    — задача в FIFO-очереди, ждёт запуска воркером;
    processing — воркер отправил задачу в n8n, идёт обработка;
    completed  — n8n успешно завершил обработку (callback);
    error      — ошибка обработки (callback от n8n) либо страховочный таймаут.
    """

    WAITING = "waiting"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"


# Итоговые (терминальные) статусы: их ставит n8n через callback или воркер по таймауту.
TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset({TaskStatus.COMPLETED, TaskStatus.ERROR})


class SchedulerStateResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"is_active": True, "message": "Планировщик запущен"}})

    is_active: bool = Field(description="Активен ли планировщик (воркер опрашивает этот флаг)")
    message: str


class CallbackRequest(BaseModel):
    """Тело POST /api/v1/scheduler/callback — уведомление от n8n о результате обработки."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"task_id": "3f2a6c1e-9d0b-4c5a-8f7e-1a2b3c4d5e6f", "status": "completed"}
        }
    )

    task_id: UUID = Field(description="UUID задачи, переданный воркером в вебхук n8n")
    status: TaskStatus = Field(
        description=(
            "Итог обработки новости: completed (успех) или error (ошибка). "
            "waiting/processing здесь недопустимы — их управляет воркер."
        )
    )

    @field_validator("status")
    @classmethod
    def _must_be_terminal(cls, v: TaskStatus) -> TaskStatus:
        if v not in TERMINAL_STATUSES:
            raise ValueError("Callback от n8n принимает только итоговые статусы: completed | error")
        return v


class CallbackResponse(BaseModel):
    task_id: UUID
    status: TaskStatus
    updated_at: datetime


class TestTriggerResponse(BaseModel):
    """Ответ POST /api/v1/scheduler/test-trigger — ручной триггер без очереди."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "task_id": "3f2a6c1e-9d0b-4c5a-8f7e-1a2b3c4d5e6f",
                "status": "waiting",
                "n8n_status_code": 200,
                "webhook_url": "http://n8n:5678/webhook-test/start_process",
            }
        }
    )

    task_id: UUID = Field(description="Созданная задача (в БД остаётся в статусе waiting)")
    status: TaskStatus = Field(description="Статус задачи после отправки запроса (waiting)")
    n8n_status_code: int = Field(description="HTTP-код ответа тестового вебхука n8n")
    webhook_url: str = Field(description="URL, на который был отправлен POST-запрос")


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    environment: str
    worker_alive: bool
    checks: dict[str, str]
