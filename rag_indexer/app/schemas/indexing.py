"""Pydantic-модели запросов/ответов API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IndexRequest(BaseModel):
    full_refresh: bool = Field(
        default=False,
        description="true = очистить kb_documents/kb_embeddings и пересобрать хранилище с нуля",
    )


class IndexStatusResponse(BaseModel):
    state: str
    total: int = 0
    processed: int = 0
    new_documents: int = 0
    new_embeddings: int = 0
    skipped_duplicates: int = 0
    errors: list[dict[str, str]] = Field(default_factory=list)
    message: str = ""
    elapsed_sec: float | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000, description="Текст запроса")
    limit: int = Field(default=5, ge=1, le=50)
    min_similarity: float | None = Field(default=None, ge=0, le=1)


class SearchHit(BaseModel):
    document_id: str
    source_path: str
    concept_id: str
    title: str | None = None
    category: str | None = None
    similarity: float
    payload: dict[str, Any]


class SearchResponse(BaseModel):
    query: str
    model: str
    hits: list[SearchHit]


class StatsResponse(BaseModel):
    documents: int
    embeddings: int
    files: int
    last_indexed_at: str | None = None


class ErrorResponse(BaseModel):
    detail: str
