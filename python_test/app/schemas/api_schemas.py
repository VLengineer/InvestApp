"""Схемы запросов/ответов API (контракт) — слой presentation."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app: str
    version: str
    environment: str
    checks: dict[str, str]


class TokenRequest(BaseModel):
    """Запрос на выдачу короткоживущего JWT (доступен только держателю admin-ключа)."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=128, description="Имя пользователя/сервиса (claim sub)")
    scopes: list[Literal["rag:read", "rag:index", "rag:admin"]] = Field(default_factory=lambda: ["rag:read"])
    ttl_seconds: int | None = Field(default=None, ge=60, le=86_400)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    scopes: list[str]


class IndexOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = Field(default=False, description="Посчитать план без записи в БД/Ollama")
    force_reindex: bool = Field(default=False, description="Пересоздать эмбеддинги даже при совпадении hash")
    limit_documents: int | None = Field(default=None, ge=1, description="Ограничить число концептов (отладка)")
    source_paths: list[str] | None = Field(default=None, description="Фильтр по относительным путям файлов")


class IndexAcceptedResponse(BaseModel):
    task_id: UUID
    status: TaskStatus
    documents_found: int
    concepts_planned: int
    message: str


class TaskView(BaseModel):
    task_id: UUID
    status: TaskStatus
    started_at: datetime | None
    finished_at: datetime | None
    total: int
    processed: int
    embedded: int
    stored_documents: int
    skipped_duplicates: int
    failed: int
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ConceptPreview(BaseModel):
    document_id: UUID | None
    concept_id: str
    title: str | None
    category: str | None
    source_path: str
    has_embedding: bool


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=8_000)
    top_k: int = Field(default=5, ge=1, le=50)
    min_similarity: float = Field(default=0.0, ge=-1.0, le=1.0)


class SearchHit(BaseModel):
    document_id: UUID
    concept_id: str
    title: str | None
    category: str | None
    source_path: str
    similarity: float
    payload: dict[str, Any]


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
