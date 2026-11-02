"""Единая точка сборки API-роутеров микросервиса (паттерн python_test)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import health, scheduler

api_router = APIRouter()
api_router.include_router(health.router)
# Управление планировщиком + callback от n8n: /api/v1/scheduler/*
api_router.include_router(scheduler.router)

__all__ = ["api_router"]
