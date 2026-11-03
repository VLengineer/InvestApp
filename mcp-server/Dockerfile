FROM python:3.12-slim

# git нужен инструменту run_local_command (status/diff/commit)
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /mcp
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 9000

# healthcheck: SSE-эндпоинт отвечает (401/404 тоже означают «сервер жив»)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
try: urllib.request.urlopen('http://127.0.0.1:9000/sse', timeout=4); sys.exit(0) \
except urllib.error.HTTPError as e: sys.exit(0 if e.code in (401,404,405) else 1) \
except Exception: sys.exit(1)"

# Запускаем FastMCP в режиме SSE сервера
CMD ["python", "server.py"]