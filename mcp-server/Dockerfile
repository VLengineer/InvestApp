FROM python:3.12

WORKDIR /mcp
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

# Запускаем FastMCP в режиме SSE сервера
CMD ["python", "server.py"]