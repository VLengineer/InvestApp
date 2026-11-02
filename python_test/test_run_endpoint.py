"""Интеграционный тест POST /run: полная индексация одним вызовом (без БД и Ollama).

Проверяет, что /run сам строит полный план по _all/kb_all.json и ОДНА фоновая задача
досчитывает все концепты до конца — повторно эндпоинт вызывать не нужно.
"""
from __future__ import annotations

import asyncio
import time
from uuid import UUID, uuid4

import jwt as pyjwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import api_router
from app.container import Container
from app.core.config import Settings
from app.main import SecurityHeadersMiddleware
from app.services.indexing_service import IndexingService
from app.services.kb_reader import KnowledgeBaseReader
from app.workers.task_registry import TaskRegistry
from app.schemas.api_schemas import TaskStatus

SECRET = "test-secret-key-0123456789abcdef-0123456789abcdef"


class FakeRepository:
    """Мини-двойник DocumentRepository без PostgreSQL."""

    def __init__(self) -> None:
        self.saved: list[tuple[str, int]] = []  # (concept_id, dim)
        self._hashes: dict[str, UUID] = {}
        self._embedded: set[UUID] = set()

    async def existing_hashes(self):
        return dict(self._hashes)

    async def embedded_document_ids(self):
        return set(self._embedded)

    async def save_with_embedding(self, concept, vector):
        doc_id = uuid4()
        self._hashes[concept.hash] = doc_id
        self._embedded.add(doc_id)
        self.saved.append((concept.concept_id, len(vector)))
        return doc_id, True

    async def stats(self):
        return {"documents": len(self._hashes), "embeddings": len(self._saved())} if False else {
            "kb_documents": len(self._hashes), "kb_embeddings": len(self.saved)}

    def _saved(self):  # noqa
        return self.saved


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, text: str) -> list[float]:
        self.calls += 1
        await asyncio.sleep(0)  # имитация сетевого запроса
        return [0.1] * 768

    async def health(self):
        return {"status": "ok", "detail": "fake"}


def main() -> None:
    settings = Settings(
        environment="test",
        jwt_secret_key=SECRET,
        kb_root="knowledge_base",
        embedding_model="test-model",
    )
    # то же приложение, что в проде (роутеры + middleware), но без подключения к реальной БД
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(api_router)
    # get_settings() в security-зависимостях должен видеть те же настройки, что и тест
    app.dependency_overrides[__import__("app.core.config", fromlist=["get_settings"]).get_settings] = lambda: settings

    fake_repo = FakeRepository()
    fake_embedder = FakeEmbedder()

    token = pyjwt.encode({"sub": "pytest", "iat": int(time.time())}, SECRET, algorithm="HS256")
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(app) as client:
        reader = KnowledgeBaseReader(settings.kb_root, common_dir_names=settings.common_dir_names)
        registry = TaskRegistry()
        indexing = IndexingService(settings, reader, fake_embedder, fake_repo, registry)
        container = Container(settings, database=None, embedder=fake_embedder, reader=reader,
                              repository=fake_repo, registry=registry, indexing=indexing)  # type: ignore[arg-type]
        client.app.state.container = container

        # 1. /run без тела — должен взять ВСЕ концепты kb_all.json (4430), лимита нет
        r = client.post("/run", headers=headers)
        assert r.status_code == 202, (r.status_code, r.text)
        body = r.json()
        print("RUN ответ:", {k: v for k, v in body.items() if k != "message"})
        assert body["concepts_total"] == 4430, body
        assert body["to_embed"] == 4430, body
        task_id = body["task_id"]

        # 2. ждём завершения ОДНОЙ фоновой задачи — она сама доходит до конца списка
        for _ in range(600):
            t = client.get(f"/index/tasks/{task_id}", headers=headers)
            assert t.status_code == 200, t.text
            snap = t.json()
            if snap["status"] in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(0.05)
        print("ФИНИШ задачи:", {k: snap[k] for k in
              ("status", "total", "processed", "stored_documents", "skipped_duplicates", "failed")})
        assert snap["status"] == TaskStatus.SUCCEEDED.value, snap["errors"][:3]
        assert snap["total"] == 4430 and snap["processed"] == 4430, snap
        assert snap["stored_documents"] == 4430, snap
        assert fake_embedder.calls == 4430, fake_embedder.calls
        assert len(fake_repo.saved) == 4430

        # 3. повторный /run — идемпотентность: всё уже проиндексировано, к обработке 0
        calls_before = fake_embedder.calls
        r2 = client.post("/run", headers=headers)
        assert r2.status_code == 202, r2.text
        b2 = r2.json()
        print("ВТОРОЙ RUN:", {k: v for k, v in b2.items() if k != "message"})
        assert b2["already_indexed"] == 4430, b2
        assert b2["to_embed"] == 0, b2
        time.sleep(0.3)
        assert fake_embedder.calls == calls_before, "повторный /run не должен ничего эмбеддить"

        # 4. /run с force_reindex=true — пересчитывает заново все 4430
        r3 = client.post("/run", json={"force_reindex": True}, headers=headers)
        assert r3.status_code == 202, r3.text
        b3 = r3.json()
        assert b3["to_embed"] == 4430, b3
        # сразу после принятия (задача активна) параллельный /run обязан получить 409
        rpar = client.post("/run", headers=headers)
        assert rpar.status_code == 409, (rpar.status_code, rpar.text)
        print("Параллельный /run -> 409 OK")
        # отменим эту задачу, чтобы не ждать второй полной индексации в тесте
        rc = client.post(f"/index/tasks/{b3['task_id']}/cancel", headers=headers)
        assert rc.status_code == 200, rc.text

        # 5. без токена — 401/403
        r5 = client.post("/run")
        assert r5.status_code in (401, 403), r5.status_code

    print("\nВСЕ ПРОВЕРКИ /run ПРОЙДЕНЫ ✅")


if __name__ == "__main__":
    main()
