"""Фоновый воркер планировщика: бесконечный цикл опроса n8n через очередь задач в БД.

Архитектура (паттерн Callback, см. диаграмму последовательности):
  1. Пока ``scheduler_state.is_active == false`` — короткая пауза (5 с) и повтор.
  2. При активной работе: создаёт задачу (uuid, status='pending') в PostgreSQL,
     отправляет POST на вебхук n8n c Bearer-токеном и ЖДЁТ callback: каждые
     POLL_INTERVAL_S читает статус задачи из БД.
  3. completed -> пауза 10 минут; rejected -> пауза 5 минут; затем шаг 1.

Ключевые решения:
  * Состояние (pending/completed/rejected) живёт в БД, а не в памяти — API-слой
    (callback-эндпоинт) и воркер общаются через таблицу tasks, что переживает
    рестарты контейнера и позволяет горизонтально масштабировать HTTP-часть.
  * Никаких блокирующих вызовов: только asyncio.sleep / asyncpg / httpx.AsyncClient.
  * Ошибки (БД недоступна, n8n не отвечает) НЕ роняют цикл: задача остаётся
    pending (или помечается rejected при явном отказе доставки), воркер делает
    экспоненциальную паузу и продолжает — устойчивость к сбоям важнее скорости.
  * Таймаут ожидания callback (task_wait_timeout_s) — страховка от «вечного»
    pending, если n8n так и не вызовет callback.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID, uuid4

import httpx

from app.core.config import Settings
from app.db.repository import SchedulerRepository

logger = logging.getLogger(__name__)


class SchedulerWorker:
    """Один экземпляр воркера на процесс; запускается из lifespan приложения."""

    def __init__(self, settings: Settings, repository: SchedulerRepository) -> None:
        self._settings = settings
        self._repo = repository
        self._task: asyncio.Task | None = None
        # Общий AsyncClient переиспользует соединения (keep-alive); создаём лениво,
        # чтобы клиент жил внутри запущенного event loop.
        self._client: httpx.AsyncClient | None = None

    # ------------------------------ Жизненный цикл ----------------------------
    async def start(self) -> None:
        """Создаёт фоновую asyncio-задачу (вызывается из lifespan startup)."""
        if self._task is not None and not self._task.done():
            logger.warning("Воркер уже запущен — повторный start игнорируется")
            return
        # Санация «зависших» pending после предыдущего падения контейнера.
        try:
            await self._repo.mark_stale_pending_rejected(self._settings.task_wait_timeout_s)
        except Exception as exc:  # noqa: BLE001 - старт важнее санации
            logger.error("Санация pending-задач не удалась (не критично): %s", exc)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._settings.n8n_request_timeout_s),
        )
        self._task = asyncio.create_task(self._run_forever(), name="scheduler-worker")
        logger.info("Воркер планировщика запущен (poll=%ds)", self._settings.poll_interval_s)

    @property
    def alive(self) -> bool:
        return self._task is not None and not self._task.done()

    async def stop(self) -> None:
        """Отменяет фоновую задачу и закрывает HTTP-клиент (lifespan shutdown)."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        logger.info("Воркер планировщика остановлен")

    # --------------------------------- Цикл -----------------------------------
    async def _run_forever(self) -> None:
        """Главный цикл: все исключения перехватываются — цикл не должен умирать."""
        while True:
            try:
                await self._run_one_cycle()
            except asyncio.CancelledError:
                raise  # штатная остановка приложения — отдаём наверх
            except Exception as exc:  # noqa: BLE001
                # Любая ошибка (БД/HTTP) — пауза и продолжение, чтобы не сломать цикл.
                logger.exception("Ошибка в цикле воркера (%s): %s — пауза 30 с и повтор", exc.__class__.__name__, exc)
                await asyncio.sleep(30)

    async def _run_one_cycle(self) -> None:
        # Шаг 1: активен ли планировщик?
        is_active = await self._repo.get_is_active()
        if not is_active:
            await asyncio.sleep(self._settings.inactive_check_interval_s)
            return

        # Шаг 2a-b: новая задача 'pending' в очереди (uuid генерируем здесь —
        # он же ключ идемпотентности для callback).
        task_id: UUID = uuid4()
        await self._repo.create_task(task_id)

        # Шаг 2c-d: запуск процесса в n8n.
        launched = await self._send_to_n8n(task_id)
        if not launched:
            # n8n недоступен/ошибка доставки: задача остаётся 'pending' (видно в БД),
            # но цикл не зависает в ожидании — пауза как для rejected (5 мин).
            logger.warning("Задача %s: n8n не принял запуск — остаётся pending, пауза %d с",
                           task_id, self._settings.sleep_after_rejected_s)
            await asyncio.sleep(self._settings.sleep_after_rejected_s)
            return

        logger.info("Задача %s отправлена в n8n, ожидание результата...", task_id)

        # Шаг 2e-g: polling статуса в БД каждые poll_interval_s (ожидание callback).
        final_status = await self._wait_for_callback(task_id)

        if final_status == "completed":
            logger.info("Задача %s успешно завершена. Ожидание 10 минут перед следующим запуском.", task_id)
            await asyncio.sleep(self._settings.sleep_after_completed_s)
        elif final_status == "rejected":
            logger.info("Задача %s отклонена. Ожидание 5 минут перед следующим запуском.", task_id)
            await asyncio.sleep(self._settings.sleep_after_rejected_s)
        else:
            # Задача исчезла из БД (ручная чистка) — считаем это мягким reject.
            logger.warning("Задача %s не найдена в БД во время опроса — пауза 5 минут.", task_id)
            await asyncio.sleep(self._settings.sleep_after_rejected_s)

    # ---------------------------------- n8n ------------------------------------
    async def _send_to_n8n(self, task_id: UUID) -> bool:
        """POST {task_id} на вебхук n8n с Bearer-токеном. True — если принят (2xx)."""
        assert self._client is not None, "AsyncClient не создан (start() не вызван)"
        headers = {"Content-Type": "application/json"}
        if self._settings.n8n_webhook_jwt_token:
            headers["Authorization"] = f"Bearer {self._settings.n8n_webhook_jwt_token}"
        try:
            response = await self._client.post(
                self._settings.n8n_webhook_url,
                json={"task_id": str(task_id)},
                headers=headers,
            )
        except httpx.HTTPError as exc:
            logger.error("Задача %s: запрос к n8n (%s) не выполнен: %s",
                         task_id, self._settings.n8n_webhook_url, exc)
            return False

        if response.status_code // 100 != 2:
            logger.error("Задача %s: n8n ответил HTTP %s: %.200s",
                         task_id, response.status_code, response.text)
            return False

        # Штатный ответ n8n-workflow: {"status": true, "description": "launched"}.
        try:
            body = response.json()
        except ValueError:
            body = {}
        if isinstance(body, dict) and body.get("status") is False:
            logger.error("Задача %s: n8n отклонил запуск: %s", task_id, body)
            return False
        logger.debug("Задача %s: ответ n8n: %.200s", task_id, response.text)
        return True

    # ------------------------------ Ожидание callback ---------------------------
    async def _wait_for_callback(self, task_id: UUID) -> str | None:
        """Polling статуса задачи в БД каждые poll_interval_s, пока не completed/rejected.

        Возвращает итоговый статус или None (задача пропала), либо 'timeout'-как-'rejected':
        по истечении task_wait_timeout_s задача помечается rejected и возвращается
        'rejected' — цикл освобождается, БД остаётся консистентной.
        """
        waited = 0
        poll = self._settings.poll_interval_s
        timeout = self._settings.task_wait_timeout_s
        while True:
            status = await self._repo.get_task_status(task_id)
            if status in ("completed", "rejected"):
                return status
            if status is None:
                return None
            if waited >= timeout:
                logger.warning(
                    "Задача %s: callback не получен за %d с — помечаем rejected (страховочный таймаут)",
                    task_id, timeout,
                )
                await self._repo.update_task_status(task_id, "rejected")
                return "rejected"
            await asyncio.sleep(poll)
            waited += poll
