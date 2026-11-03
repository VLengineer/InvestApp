# RAG-индексатор базы знаний (FastAPI + PostgreSQL/pgvector + Ollama)
FROM python:3.12

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# Каждый микросервис — своя папка внутри python_test (см. MICROSERVICES.md);
# все такие папки копируются в образ одним блоком ниже.
COPY knowledge_base ./knowledge_base
# Данные микросервиса company_profiles: cp.json (путь фиксирован в конфиге —
# COMPANY_PROFILES_JSON / DEFAULT_CP_JSON, эндпоинт /ingest его не принимает).
COPY company_profiles ./company_profiles

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8100/live', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
