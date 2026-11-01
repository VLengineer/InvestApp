"""Конфигурация сервиса (12-Factor): всё только из переменных окружения.

Секреты (JWT, пароль БД) никогда не хранятся в коде и не коммитятся:
в репозитории есть только ``.env.example`` с плейсхолдерами.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ----------------------------- Приложение ------------------------------
    app_name: str = "rag-indexer"
    app_version: str = "1.0.0"
    environment: str = Field(default="development", pattern="^(development|staging|production|test)$")
    log_level: str = Field(default="INFO")

    # ------------------------------- Безопасность ---------------------------
    # JWT-секрет генерируется ОПЕРАТОРОМ заранее, например:
    #   python -c "import secrets; print(secrets.token_urlsafe(48))"
    jwt_secret_key: str = Field(min_length=32, description="HS256 секрет для проверки JWT (env: JWT_SECRET_KEY)")
    jwt_algorithm: str = "HS256"
    jwt_issuer: str | None = Field(default=None, description="Ожидаемый claim iss (env: JWT_ISSUER)")
    jwt_audience: str | None = Field(default=None, description="Ожидаемый claim aud (env: JWT_AUDIENCE)")
    access_token_ttl_s: int = Field(default=3600, ge=60, le=86_400)
    api_keys: list[str] = Field(default_factory=list, description="Ключи X-API-Key для машинных вызовов (env: API_KEYS)")

    # ------------------------------ Knowledge base --------------------------
    kb_root: Path = Path("/app/knowledge_base")
    # «только общие json» — файлы из подпапок вида ".../Общий json/*.json"
    common_dir_names: list[str] = Field(default_factory=lambda: ["Общий json"])

    # --------------------------------- Ollama -------------------------------
    ollama_base_url: str = "http://ollama:11435"
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768
    request_timeout_s: float = 120.0
    max_retries: int = 4
    retry_backoff_base_s: float = 0.5
    retry_max_backoff_s: float = 20.0

    # -------------------------------- PostgreSQL ----------------------------
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "vectordb"
    postgres_user: str = Field(min_length=1)
    postgres_password: str = Field(min_length=1)
    db_pool_min_size: int = 1
    db_pool_max_size: int = 10
    db_statement_timeout_ms: int = 60_000

    # ------------------------------- Индексация -----------------------------
    embed_batch_size: int = Field(default=16, ge=1, le=128)
    index_concurrency: int = Field(default=2, ge=1, le=16)
    max_chunk_chars: int = Field(default=8_000, ge=256)

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        return v.upper()

    @field_validator("api_keys", mode="before")
    @classmethod
    def _split_api_keys(cls, v: object) -> object:
        """API_KEYS допускает как JSON-список, так и строку через запятую."""
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                return stripped
            return [k.strip() for k in stripped.split(",") if k.strip()]
        return v

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dsn(self) -> str:
        """DSN всегда собирается из частей — пароль не светится в одном env-поле."""
        from urllib.parse import quote

        return (
            f"postgresql://{quote(self.postgres_user)}:{quote(self.postgres_password)}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Единственный источник настроек; кэшируется (паттерн Service Locator без глобалей)."""
    return Settings()  # type: ignore[call-arg]
