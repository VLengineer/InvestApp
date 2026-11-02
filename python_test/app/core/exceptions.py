"""Доменные исключения. Слой API переводит их в HTTP-коды (global exception handler)."""

from __future__ import annotations


class AppError(Exception):
    """Базовое исключение приложения."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str = "Внутренняя ошибка", *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigError(AppError):
    status_code = 500
    code = "config_error"


class SecurityError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ValidationError_(AppError):
    status_code = 422
    code = "validation_error"


class KnowledgeBaseError(AppError):
    status_code = 422
    code = "knowledge_base_error"


class EmbeddingError(AppError):
    status_code = 502
    code = "embedding_upstream_error"


class DatabaseError(AppError):
    status_code = 500
    code = "database_error"


class TaskConflictError(AppError):
    status_code = 409
    code = "task_conflict"
