"""Тестовый эндпоинт ручного триггера процесса в n8n (без фоновой очереди).

``POST /api/v1/scheduler/test-trigger`` (защищён JWT, как основные эндпоинты):
  1. Создаёт новую задачу в БД со статусом ``waiting``.
  2. Синхронно (один раз) отправляет POST на тестовый вебхук n8n
     ``http://n8n:5678/webhook-test/start_process`` телом ``{"task_id": "<uuid>"}``.
  3. Возвращает ``task_id`` и HTTP-код ответа n8n.

Логика НЕ использует фоновую очередь: нет polling, нет ожидания callback —
просто создать задачу, отправить запрос и остановиться. Задача остаётся
``waiting`` в таблице tasks; если планировщик активен, воркер подхватит её
позже по своим правилам FIFO (это не мешает одноразовому ручному тесту).
"""

from __future__ import annotations

import logging
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, status

from app.api.deps import RepositoryDep, SettingsDep
from app.core.security import PrincipalDep
from app.schemas.scheduler import TaskStatus, TestTriggerResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/scheduler", tags=["scheduler-test"])


@router.post(
    "/test-trigger",
    response_model=TestTriggerResponse,
    summary="Ручной тестовый запуск процесса в n8n (JWT, без очереди и ожидания)",
    description=(
        "Создаёт задачу (status='waiting') и ОДИН раз отправляет POST на тестовый "
        "вебхук n8n (N8N_TEST_WEBHOOK_URL, по умолчанию "
        "http://n8n:5678/webhook-test/start_process) с телом {\"task_id\": \"<uuid>\"}. "
        "Цикл ожидания НЕ запускается: polling и callback не используются."
    ),
)
async def test_trigger(
    repository: RepositoryDep,
    settings: SettingsDep,
    _principal: PrincipalDep,
) -> TestTriggerResponse:
    """Одноразовый ручной триггер: INSERT waiting -> POST в n8n -> ответ."""
    task_id = uuid4()
    await repository.create_task(task_id)  # статус 'waiting' — как у обычной очереди

    headers = {"Content-Type": "application/json"}
    if settings.n8n_webhook_jwt_token:
        headers["Authorization"] = f"Bearer {settings.n8n_webhook_jwt_token}"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.n8n_request_timeout_s)) as client:
            response = await client.post(
                settings.n8n_test_webhook_url,
                json={"task_id": str(task_id)},
                headers=headers,
            )
    except httpx.HTTPError as exc:
        # Тестовый хэндлер: падаем 502 — оператор видит причину в ответе/логе.
        logger.error("test-trigger: запрос к n8n (%s) не выполнен: %s",
                     settings.n8n_test_webhook_url, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Тестовый вебхук n8n недоступен: {exc.__class__.__name__}: {exc}",
        ) from exc

    logger.info("test-trigger: задача %s -> POST %s ответил HTTP %s",
                task_id, settings.n8n_test_webhook_url, response.status_code)
    return TestTriggerResponse(
        task_id=task_id,
        status=TaskStatus.WAITING,
        n8n_status_code=response.status_code,
        webhook_url=settings.n8n_test_webhook_url,
    )
