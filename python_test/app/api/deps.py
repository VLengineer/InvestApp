"""Зависимости API-слоя (adapter между FastAPI DI и Composition Root)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.container import Container
from app.core.config import Settings, get_settings
from app.repositories.document_repository import DocumentRepository
from app.services.indexing_service import IndexingService
from app.services.kb_reader import KnowledgeBaseReader
from app.workers.task_registry import TaskRegistry
from news_analyzer.repository import NewsRepository
from news_analyzer.service import NewsAnalyzerService


def get_container(request: Request) -> Container:
    container: Container | None = getattr(request.app.state, "container", None)
    if container is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Сервис ещё не готов")
    return container


ContainerDep = Annotated[Container, Depends(get_container)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_indexing_service(container: ContainerDep) -> IndexingService:
    return container.indexing


def get_registry(container: ContainerDep) -> TaskRegistry:
    return container.registry


def get_reader(container: ContainerDep) -> KnowledgeBaseReader:
    return container.reader


def get_repository(container: ContainerDep) -> DocumentRepository:
    return container.repository


IndexingDep = Annotated[IndexingService, Depends(get_indexing_service)]
RegistryDep = Annotated[TaskRegistry, Depends(get_registry)]
ReaderDep = Annotated[KnowledgeBaseReader, Depends(get_reader)]
RepositoryDep = Annotated[DocumentRepository, Depends(get_repository)]


# ---------------- Микросервис news_analyzer (код: python_test/news_analyzer) ---
def get_news_repository(container: ContainerDep) -> NewsRepository:
    return container.news_repository


def get_news_analyzer_service(container: ContainerDep) -> NewsAnalyzerService:
    return container.news_analyzer


NewsRepositoryDep = Annotated[NewsRepository, Depends(get_news_repository)]
NewsAnalyzerDep = Annotated[NewsAnalyzerService, Depends(get_news_analyzer_service)]
