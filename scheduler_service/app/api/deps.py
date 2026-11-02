"""Зависимости API-слоя scheduler_service (паттерн python_test/app/api/deps.py):
объекты живут в app.state (собираются в lifespan), зависимости — тонкие геттеры."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings
from app.db.database import Database
from app.db.repository import SchedulerRepository
from app.workers.scheduler_worker import SchedulerWorker

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_database(request: Request) -> Database:
    database: Database | None = getattr(request.app.state, "database", None)
    if database is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="БД ещё не подключена")
    return database


def get_repository(request: Request) -> SchedulerRepository:
    repository: SchedulerRepository | None = getattr(request.app.state, "repository", None)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Репозиторий ещё не готов")
    return repository


def get_worker(request: Request) -> SchedulerWorker:
    worker: SchedulerWorker | None = getattr(request.app.state, "worker", None)
    if worker is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Воркер ещё не запущен")
    return worker


DatabaseDep = Annotated[Database, Depends(get_database)]
RepositoryDep = Annotated[SchedulerRepository, Depends(get_repository)]
WorkerDep = Annotated[SchedulerWorker, Depends(get_worker)]
