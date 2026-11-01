"""Единая точка сборки API-роутеров микросервиса."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import health, news, rag

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(rag.router)
# Микросервис news_analyzer: эндпоинты здесь, код — в python_test/news_analyzer/
api_router.include_router(news.router)

__all__ = ["api_router"]
