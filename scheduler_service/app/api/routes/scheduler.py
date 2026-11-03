"""Эндпоинты управления планировщиком и приема callback-уведомлений от n8n.

Единый API префикса проекта: /api/v1/scheduler/*.

Аутентификация повторяет паттерн python_test:
  * start/stop — JWT Bearer (app/core/security.py, тот же секрет, что у RAG-сервиса);
  * callback   — машинный эндпоинт без JWT: проверка заголовка X-Callback-Secret
    на совпадение с CALLBACK_SECRET из env (hmac.compare_digest — против timing-атак).
"""

from __future__ import annotations

import hmac
import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.deps import RepositoryDep, SettingsDep
from app.core.security import PrincipalDep
from app.schemas.scheduler import (
    CallbackRequest,
    CallbackResponse,
    SchedulerStateResponse,
)


def verify_callback_secret(
    settings: SettingsDep,
    x_callback_secret: Annotated[str | None, Header(alias="X-Callback-Secret")] = None,
) -> None:
    """Защита машинного эндпоинта callback: сверка заголовка с CALLBACK_SECRET из env.

    compare_digest — постоянство времени сравнения (против timing-атак);
    ошибки — единое сообщение 401, без раскрытия ожидаемого значения.
    """
    if not x_callback_secret or not hmac.compare_digest(
        x_callback_secret.encode("utf-8"), settings.callback_secret.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный или отсутствующий заголовок X-Callback-Secret",
        )

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/scheduler", tags=["scheduler"])


async def _set_active(repository: Any, is_active: bool, principal: str) -> SchedulerStateResponse:
    await repository.set_is_active(is_active)
    action = "запущен" if is_active else "остановлен"
    logger.info("Планировщик %s (админ sub=%s)", action, principal)
    return SchedulerStateResponse(
        is_active=is_active,
        message=f"Планировщик {action}",
    )


@router.post(
    "/start",
    response_model=SchedulerStateResponse,
    summary="Запустить планировщик (JWT)",
    description="Устанавливает scheduler_state.is_active = true; воркер продолжит цикл с БД.",
)
async def start_scheduler(repository: RepositoryDep, principal: PrincipalDep) -> SchedulerStateResponse:
    return await _set_active(repository, True, principal)


@router.post(
    "/stop",
    response_model=SchedulerStateResponse,
    summary="Остановить планировщик (JWT)",
    description=(
        "Устанавливает scheduler_state.is_active = false. Текущая processing-задача "
        "дождется callback, но новых задач воркер запускать не будет."
    ),
)
async def stop_scheduler(repository: RepositoryDep, principal: PrincipalDep) -> SchedulerStateResponse:
    return await _set_active(repository, False, principal)


@router.get(
    "/state",
    response_model=SchedulerStateResponse,
    summary="Текущее состояние планировщика (JWT)",
)
async def get_state(repository: RepositoryDep, _principal: PrincipalDep) -> SchedulerStateResponse:
    is_active = await repository.get_is_active()
    return SchedulerStateResponse(is_active=is_active, message="ok")


@router.post(
    "/callback",
    response_model=CallbackResponse,
    summary="Приём результата обработки задачи от n8n (X-Callback-Secret)",
    description=(
        "Вызывается сценарием n8n по завершении проверки новости: "
        "{\"task_id\": \"<uuid>\", \"status\": \"completed\" | \"error\"} "
        "и заголовок X-Callback-Secret. Воркер увидит новый статус при следующем polling "
        "и запустит следующую waiting-задачу."
    ),
)
async def n8n_callback(
    body: CallbackRequest,
    repository: RepositoryDep,
    _secret: Annotated[None, Depends(verify_callback_secret)],
) -> CallbackResponse:
    """Обновляет итоговый статус задачи; воркер подхватит его на следующем polling-цикле."""
    updated = await repository.update_task_status(body.task_id, body.status.value)
    if updated is None:
        # 404 даёт сигнал n8n, что task_id неизвестен (например, задача уже ссанитизирована).
        logger.warning("Callback по неизвестной задаче %s (status=%s)", body.task_id, body.status)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Задача {body.task_id} не найдена",
        )
    logger.info("Callback: задача %s -> %s", body.task_id, body.status)
    return CallbackResponse(
        task_id=updated["id"],
        status=updated["status"],
        updated_at=updated["updated_at"],
    )


@router.get(
    "/tasks/{task_id}",
    summary="Статус задачи по uuid (JWT) — для отладки цепочки",
)
async def get_task_status(
    task_id: str,
    repository: RepositoryDep,
    _principal: PrincipalDep,
) -> dict[str, Any]:
    try:
        parsed = UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="task_id должен быть UUID")
    current = await repository.get_task_status(parsed)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Задача {task_id} не найдена")
    return {"task_id": str(parsed), "status": current}
