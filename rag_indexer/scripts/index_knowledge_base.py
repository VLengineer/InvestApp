#!/usr/bin/env python3
"""CLI-скрипт построения RAG-хранилища из knowledge_base (PostgreSQL + pgvector).

Делает ровно то, что требуется задачей:
  * берёт все *.json из папки knowledge_base и её подпапок;
  * каждый JSON-объект-концепт = документ (чанки не нужны);
  * эмбеддинги — через Ollama (модель embeddinggemma-2);
  * пишет в две таблицы: kb_documents (документ + uuid) и kb_embeddings (вектор + uuid документа).

Примеры:
    # только предпросмотр структуры (без БД и Ollama)
    python -m scripts.index_knowledge_base --kb-dir ../knowledge_base --dry-run

    # полная индексация
    DATABASE_URL=postgresql://user:pass@localhost:5432/vectordb \\
    OLLAMA_BASE_URL=http://localhost:11435/api \\
    python -m scripts.index_knowledge_base --kb-dir ../knowledge_base

    # пересборка с нуля (TRUNCATE) + свои лимиты
    python -m scripts.index_knowledge_base --full-refresh --limit 100 --batch-size 8
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# чтобы модуль можно было запускать и как скрипт (python scripts/index_knowledge_base.py)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.services.embedder import OllamaEmbedder  # noqa: E402
from app.services.loader import load_concepts  # noqa: E402
from app.services.storage import RagStorage, _vec_literal  # noqa: E402

log = logging.getLogger("rag_indexer.cli")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Индексация knowledge_base (*.json) в RAG-хранилище PostgreSQL + pgvector",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--kb-dir", default=settings.knowledge_base_dir,
                        help="каталог базы знаний (обход рекурсивный)")
    parser.add_argument("--database-url", default=settings.database_url,
                        help="DSN PostgreSQL (или переменная окружения DATABASE_URL)")
    parser.add_argument("--ollama-url", default=settings.ollama_base_url,
                        help="базовый URL Ollama API")
    parser.add_argument("--model", default=settings.ollama_embed_model,
                        help="модель эмбеддингов Ollama")
    parser.add_argument("--dim", type=int, default=settings.embedding_dim,
                        help="ожидаемая размерность вектора (проверяется по факту)")
    parser.add_argument("--batch-size", type=int, default=settings.embed_batch_size,
                        help="текстов за один запрос к Ollama")
    parser.add_argument("--concurrency", type=int, default=settings.index_concurrency,
                        help="параллельных запросов к Ollama")
    parser.add_argument("--limit", type=int, default=0,
                        help="индексировать только первые N документов (0 = все)")
    parser.add_argument("--full-refresh", action="store_true",
                        help="очистить обе таблицы перед индексацией")
    parser.add_argument("--skip-existing", action="store_true",
                        help="не запрашивать эмбеддинги для документов, у которых он уже есть")
    parser.add_argument("--dry-run", action="store_true",
                        help="только разобрать JSON и показать статистику (БД/Ollama не трогать)")
    parser.add_argument("--report", default=None, help="сохранить отчёт в JSON-файл")
    parser.add_argument("-v", "--verbose", action="store_true", help="отладочный лог")
    return parser.parse_args(argv)


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )


async def run(args: argparse.Namespace) -> dict:
    kb_dir = Path(args.kb_dir).resolve()
    if not kb_dir.is_dir():
        raise SystemExit(f"Каталог базы знаний не найден: {kb_dir}")

    report_obj = load_concepts(kb_dir, get_settings().max_json_file_size_mb)
    concepts = report_obj.concepts
    if args.limit and args.limit > 0:
        concepts = concepts[: args.limit]

    summary: dict = {
        "kb_dir": str(kb_dir),
        "files_scanned": report_obj.files_scanned,
        "files_ok": report_obj.files_ok,
        "documents_found": len(concepts),
        "load_errors": report_obj.errors,
        "model": args.model,
    }

    if args.dry_run:
        sizes = sorted((len(c.text) for c in concepts), reverse=True)
        summary["text_chars_max"] = sizes[0] if sizes else 0
        summary["text_chars_median"] = sizes[len(sizes) // 2] if sizes else 0
        summary["sample"] = [c.as_dict() for c in concepts[:5]]
        log.info("dry-run: %d документов готовы к индексации", len(concepts))
        return summary

    storage = RagStorage(args.database_url, min_size=1, max_size=max(2, args.concurrency))
    await storage.open(timeout=60)
    embedder = OllamaEmbedder(
        base_url=args.ollama_url, model=args.model, timeout=get_settings().embed_request_timeout,
        max_retries=get_settings().embed_max_retries, expected_dim=args.dim,
        concurrency=max(1, args.concurrency),
    )
    try:
        await storage.ensure_schema(args.dim)
        dim = await storage.check_embedding_dim(args.dim)
        log.info("Схема готова (размерность embedding: %s)", dim or args.dim)

        if args.full_refresh:
            log.warning("--full-refresh: очищаю kb_documents и kb_embeddings")
            await storage.truncate_all()

        if args.skip_existing:
            hashes = await storage.indexed_hashes(args.model)
            before = len(concepts)
            concepts = [c for c in concepts if c.content_hash not in hashes]
            existing = before - len(concepts)
            log.info("Пропущено документов с существующим эмбеддингом: %d", existing)
            summary["skipped_existing"] = existing

        ids_by_hash = await storage.upsert_documents(concepts)
        new_docs = sum(1 for c in concepts if c.content_hash in ids_by_hash)
        summary["documents_new"] = new_docs
        summary["documents_duplicated"] = len(concepts) - new_docs

        pending = [c for c in concepts if c.text.strip()]
        batch_size = max(1, args.batch_size)
        stored = 0
        errors: list[dict] = []
        for i in range(0, len(pending), batch_size):
            batch = pending[i : i + batch_size]
            try:
                vectors = await embedder.embed([c.text for c in batch])
            except Exception as exc:  # noqa: BLE001
                log.error("Батч %d-%d: %s", i, i + len(batch), exc)
                errors.append({"batch_start": i, "error": str(exc)})
                continue
            rows = [
                (ids_by_hash[c.content_hash], _vec_literal(v), 0)
                for c, v in zip(batch, vectors)
                if c.content_hash in ids_by_hash
            ]
            stored += await storage.save_embeddings(rows, model=args.model)
            log.info("Эмбеддинги сохранено: %d/%d", min(i + batch_size, len(pending)), len(pending))

        summary.update({"embeddings_stored": stored, "embedding_errors": errors,
                        "stats_after": await storage.stats()})
        log.info("Готово: %s", json.dumps(summary["stats_after"], ensure_ascii=False, default=str))
        return summary
    finally:
        await embedder.aclose()
        await storage.close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)
    try:
        summary = asyncio.run(run(args))
    except KeyboardInterrupt:
        log.error("Прервано пользователем")
        return 130
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    text = json.dumps(summary, ensure_ascii=False, indent=2, default=str)
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
        log.info("Отчёт сохранён: %s", args.report)
    print(text)
    return 1 if summary.get("documents_found", 0) == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
