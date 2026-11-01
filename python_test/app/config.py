"""Конфигурация микросервиса индексации базы знаний (RAG).

Все параметры читаются из переменных окружения / файла .env (см. .env.example).
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- PostgreSQL + pgvector ---
    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/vectordb",
        description="Строка подключения к PostgreSQL (psycopg DSN)",
    )
    db_pool_min_size: int = 1
    db_pool_max_size: int = 5

    # --- Ollama (эмбеддинги) --- внутри docker-сети ollama слушает 11435 (OLLAMA_PORT в docker-compose.yml)
    ollama_base_url: str = "http://ollama:11435/api"
    ollama_embed_model: str = "embeddinggemma-2"
    embedding_dim: int = 768          # ожидаемая размерность (проверяется при старте)
    embed_batch_size: int = 8         # текстов за один запрос к Ollama
    embed_request_timeout: int = 120  # секунды
    embed_max_retries: int = 3

    # --- Каталог базы знаний ---
    knowledge_base_dir: str = "/data/knowledge_base"
    max_json_file_size_mb: int = 10

    # --- Прочее ---
    index_concurrency: int = 2        # параллельных батча эмбеддингов
    jwt_secret: str | None = None     # если задан — эндпоинты API требуют Bearer JWT
    jwt_algorithm: str = "HS256"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
