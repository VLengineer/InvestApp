"""Фоновый воркер планировщика: непрерывный polling очереди задач + запуск n8n.

Архитектура (паттерн Callback, очередь FIFO, 4 статуса):
    waiting -> processing (воркер) -> completed | error (n8n через callback)

Алгоритм одного шага цикла (непрерывный polling таблицы tasks):
  a) Есть ли сейчас задача в статусе ``processing``? Если да — ждём её итога:
     каждые ``poll_interval_s`` читаем статус из БД, пока n8n не переведёт
     задачу в ``completed``/``error`` (или не сработает страховочный таймаут).
  b) Если задач в ``processing`` нет — берём самую старую ``waiting``
     (ORDER BY created_at ASC LIMIT 1; задачи создаёт API/тестовый триггер).
  c) Атомарно переводим её в ``processing`` и отправляем POST в n8n.
  d) Ожидаем завершения (callback или таймаут), затем шаг a) для следующей задачи.

Ключевые решения:
  * Состояние очереди живёт в БД, а не в памяти — API-слой (callback-эндпоинт,
    test-trigger) и воркер общаются только через таблицу tasks; это переживает
    рестарты контейнера и позволяет горизонтально масштабировать HTTP-часть.
  * Задачи создаются со статусом ``waiting`` НЕЗАВИСИМО от того, чем закончилась
    предыдущая: воркер сам разгребает очередь по одной задаче за раз (FIFO).
  * Итоговые статусы ``completed``/``error`` ставит сама n8n через callback;
    воркер их только проверяет (polling) и по завершении запускает следующую.
  * Никаких блокирующих вызовов: только asyncio.sleep / asyncpg / httpx.AsyncClient.
  * Страховочные таймауты сохранены: «зависшая» processing старше
    ``task_wait_timeout_s`` помечается ``error`` (при старте — массовая санация,
    в polling — построчно), после чего цикл освобождается.
  * Ошибки (БД недоступна, n8n не отвечает) НЕ роняют цикл: пауза и продолжение —
    устойчивость к сбоям важнее скорости.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx

from app.core.config import Settings
from app.db.repository import SchedulerRepository
from app.schemas.scheduler import TaskStatus

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
        # Санация «зависших» processing после предыдущего падения контейнера.
        try:
            await self._repo.mark_stale_processing_error(self._settings.task_wait_timeout_s)
        except Exception as exc:  # noqa: BLE001 - старт важнее санации
            logger.error("Санация processing-задач не удалась (не критично): %s", exc)
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
        """Один шаг непрерывного polling'а таблицы tasks (см. docstring модуля)."""
        # Шаг 0: активен ли планировщик?
        is_active = await self._repo.get_is_active()
        if not is_active:
            await asyncio.sleep(self._settings.inactive_check_interval_s)
            return

        # Шаг a: есть ли прямо сейчас задача в processing? Ждём её итога.
        current = await self._repo.get_processing_task()
        if current is not None:
            final_status = await self._wait_for_callback(current["id"], started_at=current["created_at"])
            await self._handle_final_status(current["id"], final_status)
            return

        # Шаг b: в работе пусто — берём самую старую waiting (FIFO).
        task_id = await self._repo.get_next_waiting_task()
        if task_id is None:
            # Очередь пуста: короткий idle-polling, новых задач нет.
            await asyncio.sleep(self._settings.idle_poll_interval_s)
            return

        # Шаг c: атомарный захват waiting -> processing.
        claimed = await self._repo.claim_task(task_id)
        if claimed is None:
            # Задачу забрал другой воркер (или она исчезла) — сразу следующий шаг.
            return

        # Шаг c (продолжение): запуск процесса в n8n.
        launched = await self._send_to_n8n(task_id)
        if not launched:
            # n8n недоступен/ошибка доставки: снимаем с обработки обратно в waiting —
            # задача будет переброшена позже (страховка от вечного retry — таймаут санации).
            logger.warning("Задача %s: n8n не принял запуск — возвращаем в waiting, пауза %d с",
                           task_id, self._settings.sleep_after_error_s)
            await self._repo.update_task_status(task_id, TaskStatus.WAITING.value)
            await asyncio.sleep(self._settings.sleep_after_error_s)
            return

        logger.info("Задача %s отправлена в n8n, ожидание результата...", task_id)

        # Шаг d: polling статуса в БД каждые poll_interval_s (ожидание callback).
        final_status = await self._wait_for_callback(task_id)
        await self._handle_final_status(task_id, final_status)

    async def _handle_final_status(self, task_id: UUID, final_status: str | None) -> None:
        """Пауза по итогу задачи; следующая waiting будет взята на следующем шаге цикла."""
        if final_status == TaskStatus.COMPLETED.value:
            logger.info("Задача %s завершена (completed). Пауза %d с перед следующим запуском.",
                        task_id, self._settings.sleep_after_completed_s)
            await asyncio.sleep(self._settings.sleep_after_completed_s)
        elif final_status == TaskStatus.ERROR.value:
            logger.info("Задача %s завершилась с ошибкой (error). Пауза %d с перед следующим запуском.",
                        task_id, self._settings.sleep_after_error_s)
            await asyncio.sleep(self._settings.sleep_after_error_s)
        else:
            # Задача исчезла из БД (ручная чистка) — пауза как для error.
            logger.warning("Задача %s не найдена в БД во время опроса — пауза %d минут.",
                           task_id, self._settings.sleep_after_error_s // 60 or 1)
            await asyncio.sleep(self._settings.sleep_after_error_s)

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
    async def _wait_for_callback(self, task_id: UUID, started_at=None) -> str | None:
        """Polling статуса задачи в БД каждые poll_interval_s, пока completed/error.

        Возвращает итоговый статус ('completed' | 'error'), либо None (задача
        пропала из БД). Страховочный таймаут: если задача висит в processing
        дольше task_wait_timeout_s (callback так и не пришёл — n8n упал),
        воркер помечает её 'error' и возвращает 'error' — цикл освобождается
        и на следующем шаге берёт следующую waiting-задачу.

        started_at — время начала обработки (для задач, найденных уже в
        processing при рестарте воркера); для свежезахваченной считаем от now.
        """
        poll = self._settings.poll_interval_s
        timeout = self._settings.task_wait_timeout_s
        waited = 0
        if started_at is not None:
            # Чужая/пережитая processing: отсчитываем таймаут от её created_at.
            age = (datetime.now(timezone.utc) - started_at).total_seconds()
            waited = max(0, int(age))
        while True:
            status = await self._repo.get_task_status(task_id)
            if status in (TaskStatus.COMPLETED.value, TaskStatus.ERROR.value):
                return status
            if status is None:
                return None
            if status != TaskStatus.PROCESSING.value:
                # Откатили вручную (например, вернули в waiting) — ждём снова.
                return None
            if waited >= timeout:
                logger.warning(
                    "Задача %s: callback не получен за %d с — помечаем error (страховочный таймаут)",
                    task_id, timeout,
                )
                await self._repo.update_task_status(task_id, TaskStatus.ERROR.value)
                return TaskStatus.ERROR.value
            await asyncio.sleep(poll)
            waited += poll
