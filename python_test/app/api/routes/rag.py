"""Основные эндпоинты RAG-сервиса: индексация, задачи, поиск, документы, статистика.

Все эндпоинты требуют авторизацию единым JWT-токеном
(``Authorization: Bearer <token>``) и проверяют нужные scopes
(rag:read / rag:index / rag:admin). Токен без scope = все права.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import ContainerDep, IndexingDep, ReaderDep, RegistryDep, RepositoryDep
from app.core.security import Principal, Scope, require_scope
from app.schemas.api_schemas import (
    ConceptPreview,
    IndexAcceptedResponse,
    IndexOptions,
    SearchHit,
    SearchRequest,
    TaskView,
)

router = APIRouter(tags=["rag"])


# ------------------------------- Индексация ----------------------------------
@router.post(
    "/index",
    response_model=IndexAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Запустить фоновую индексацию knowledge_base",
    description=(
        "Собирает концепты из папок «Общий json», пропускает уже проиндексированные "
        "(по content_hash), остальные эмбеддит через Ollama и пишет в PostgreSQL+pgvector. "
        "Возвращает task_id — прогресс смотрите в GET /index/tasks/{task_id}. "
        "Одновременно может выполняться только одна индексация (иначе 409)."
    ),
)
async def start_indexing(
    options: IndexOptions,
    indexing: IndexingDep,
    principal: Annotated[Principal, Depends(require_scope(Scope.INDEX))],
) -> IndexAcceptedResponse:
    task, summary = await indexing.start(options.model_dump(exclude_none=True), requested_by=principal.subject)
    return IndexAcceptedResponse(
        task_id=task.task_id,
        status=task.status,
        documents_found=summary["files_found"],
        concepts_planned=summary["to_embed"],
        message=(
            f"План: файлов={summary['files_found']}, концептов всего={summary['concepts_total']}, "
            f"уникальных={summary['unique_concepts']}, уже проиндексировано={summary['already_indexed']}, "
            f"к обработке={summary['to_embed']}"
        ),
    )


@router.get(
    "/index/tasks",
    response_model=list[TaskView],
    summary="Список последних задач индексации",
)
async def list_tasks(
    registry: RegistryDep,
    _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[TaskView]:
    return [TaskView(**task.snapshot()) for task in registry.list_tasks(limit=limit)]


@router.get(
    "/index/tasks/{task_id}",
    response_model=TaskView,
    summary="Статус/прогресс задачи индексации",
)
async def get_task(
    task_id: UUID,
    registry: RegistryDep,
    _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
) -> TaskView:
    task = registry.get(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    return TaskView(**task.snapshot())


@router.post(
    "/index/tasks/{task_id}/cancel",
    response_model=TaskView,
    summary="Отменить задачу индексации",
)
async def cancel_task(
    task_id: UUID,
    registry: RegistryDep,
    _principal: Annotated[Principal, Depends(require_scope(Scope.ADMIN))],
) -> TaskView:
    task = registry.get(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    await registry.cancel(task_id)
    return TaskView(**task.snapshot())


# -------------------------------- Поиск --------------------------------------
@router.post(
    "/search",
    response_model=list[SearchHit],
    summary="Семантический поиск по базе знаний",
    description=(
        "Эмбеддит запрос через Ollama (префикс `search:`) и возвращает top_k документов "
        "по косинусному сходству с pgvector (`embedding <=> query`)."
    ),
)
async def search(
    body: SearchRequest,
    container: ContainerDep,
    repository: RepositoryDep,
    _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
) -> list[SearchHit]:
    vector = await container.embedder.embed(f"search: {body.query}")
    rows = await repository.search_by_vector(vector, top_k=body.top_k, min_similarity=body.min_similarity)
    return [SearchHit(**row) for row in rows]


# ------------------------------ Документы ------------------------------------
@router.get(
    "/documents",
    response_model=list[ConceptPreview],
    summary="Список проиндексированных концептов",
)
async def list_documents(
    repository: RepositoryDep,
    _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[ConceptPreview]:
    rows = await repository.list_concepts(limit=limit)
    return [ConceptPreview(**row) for row in rows]


@router.get(
    "/sources",
    response_model=list[dict[str, Any]],
    summary="Файлы knowledge_base и число концептов в них (без БД)",
)
async def list_sources(
    reader: ReaderDep,
    _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
) -> list[dict[str, Any]]:
    sources = await reader.load()
    return [
        {"path": s.rel_path, "concepts": len(s.concepts), "error": s.error}
        for s in sources
    ]


# ------------------------------- Статистика ----------------------------------
@router.get(
    "/stats",
    response_model=dict[str, Any],
    summary="Статистика индекса (документы/эмбеддинги/индексы)",
)
async def stats(
    repository: RepositoryDep,
    _principal: Annotated[Principal, Depends(require_scope(Scope.READ))],
) -> dict[str, Any]:
    return await repository.stats()
