"""Pydantic v2-схемы API-контракта scheduler_service (presentation-слой)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TaskStatus(StrEnum):
    """Статусы задачи в очереди (совпадают с CHECK-ограничением в БД)."""

    PENDING = "pending"
    COMPLETED = "completed"
    REJECTED = "rejected"


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
    status: TaskStatus = Field(description="Итог обработки новости: completed (ценная) или rejected")


class CallbackResponse(BaseModel):
    task_id: UUID
    status: TaskStatus
    updated_at: datetime


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    environment: str
    worker_alive: bool
    checks: dict[str, str]
