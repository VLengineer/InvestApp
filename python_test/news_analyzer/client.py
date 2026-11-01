"""Клиент n8n-вебхука для микросервиса news_analyzer.

Микросервис НЕ сохраняет новость в БД сам — он пересылает JSON
``{source, title, content, ts}`` на вебхук n8n. Адрес собирается из env:
``N8N_BASE_URL`` (по умолчанию ``http://n8n:5678/``) + ``N8N_NEWS_WEBHOOK_PATH``
(по умолчанию ``/webhook/news_analizer``). Дальше — сохранение в
``market_news_ml_dataset`` и AI-анализ — делает сценарий n8n.

См. app/core/config.py (настройки) и python_test/.env (значения).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.config import Settings
from news_analyzer.schemas import NewsAnalyzeRequest

logger = logging.getLogger(__name__)


class N8nForwardError(RuntimeError):
    """Не удалось доставить новость на вебхук n8n (сеть/таймаут/HTTP 4xx-5xx)."""

    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class N8nWebhookClient:
    """Тонкий async-клиент поверх httpx: POST JSON на вебхук n8n."""

    def __init__(self, settings: Settings) -> None:
        # URL берём из env при сборке контейнера; trailing-slash не важен —
        # normalize ниже приводит к каноничному виду.
        self._webhook_url = settings.n8n_webhook_url.rstrip("/")
        if not self._webhook_url.startswith(("http://", "https://")):
            raise ValueError(
                "N8N_BASE_URL/N8N_NEWS_WEBHOOK_PATH должны давать абсолютный "
                f"http(s)-URL, получено: {self._webhook_url!r}"
            )
        self._timeout_s = settings.n8n_request_timeout_s
        self._client: httpx.AsyncClient | None = None

    @property
    def webhook_url(self) -> str:
        return self._webhook_url

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout_s)
        return self._client

    async def forward_news(self, request: NewsAnalyzeRequest) -> dict[str, Any]:
        """Отправляет новость на вебхук n8n и возвращает его ответ (JSON или текст)."""
        payload = request.model_dump(mode="json")
        logger.info(
            "news_analyzer >>> POST %s: source=%r title=%r content_len=%d ts=%s",
            self._webhook_url, request.source, request.title, len(request.content), payload["ts"],
        )
        client = self._get_client()
        try:
            response = await client.post(self._webhook_url, json=payload)
        except httpx.HTTPError as exc:
            logger.error("news_analyzer <<< ошибка транспорта до n8n: %s", exc)
            raise N8nForwardError(
                f"n8n недоступна по адресу {self._webhook_url}: {exc.__class__.__name__}: {exc}"
            ) from exc

        text = response.text
        parsed: Any
        try:
            parsed = json.loads(text) if text else None
        except ValueError:
            parsed = {"raw": text}

        if response.is_error:
            logger.error(
                "news_analyzer <<< n8n ответил HTTP %d: %.300s", response.status_code, text,
            )
            raise N8nForwardError(
                f"Вебхук n8n вернул HTTP {response.status_code}",
                status_code=response.status_code,
                body=text[:2000],
            )

        logger.info("news_analyzer <<< n8n ответил HTTP %d", response.status_code)
        return {"status_code": response.status_code, "response": parsed}

    async def health(self) -> dict[str, str]:
        """HEAD/GET-проверка доступности n8n (не самого вебхука — он живёт только во время запроса)."""
        base = self._extract_base_url(self._webhook_url)
        url = f"{base}/healthz"
        client = self._get_client()
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            return {"status": "down", "detail": f"{exc.__class__.__name__}: {exc}", "url": url}
        if response.is_success:
            return {"status": "ok", "detail": f"n8n healthz HTTP {response.status_code}", "url": url}
        return {"status": "degraded", "detail": f"n8n healthz HTTP {response.status_code}", "url": url}

    @staticmethod
    def _extract_base_url(webhook_url: str) -> str:
        """http://n8n:5678/webhook/news_analizer → http://n8n:5678"""
        proto, _, rest = webhook_url.partition("://")
        host, _, _path = rest.partition("/")
        return f"{proto}://{host}"

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
