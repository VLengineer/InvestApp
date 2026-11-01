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

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        # Точечная замена поведения: у штатных источников отключаем json.loads()
        # для сложных (list) полей — списки разбирает field_validator
        # _split_comma_lists (JSON-список либо строка через запятую).
        # Все остальные параметры источников (env_file, prefix, case_sensitive...)
        # остаются штатными.
        for source in (env_settings, dotenv_settings):
            source.decode_complex_value = lambda _field_name, _field, value: value
        return (init_settings, env_settings, dotenv_settings, file_secret_settings)

    # ----------------------------- Приложение ------------------------------
    app_name: str = "rag-indexer"
    app_version: str = "1.0.0"
    environment: str = Field(default="development", pattern="^(development|staging|production|test)$")
    log_level: str = Field(default="INFO")

    # ------------------------------- Безопасность ---------------------------
    # Единый способ доступа: один JWT (HS256) в заголовке Authorization: Bearer.
    # Admin-ключи и X-API-Key упразднены. Токен по умолчанию БЕССРОЧНЫЙ (без exp).
    # Секрет генерируется ОПЕРАТОРОМ заранее, например:
    #   python secret.py   (или python -c "import secrets; print(secrets.token_urlsafe(48))")
    jwt_secret_key: str = Field(min_length=32, description="HS256 секрет для проверки JWT (env: JWT_SECRET_KEY)")
    jwt_algorithm: str = "HS256"
    # По умолчанию iss/aud НЕ проверяются — чтобы любой корректно подписанный
    # токен принимался (меньше причин для «token is invalid» в Swagger).
    jwt_issuer: str | None = Field(default=None, description="Ожидаемый claim iss, если задан (env: JWT_ISSUER)")
    jwt_audience: str | None = Field(default=None, description="Ожидаемый claim aud, если задан (env: JWT_AUDIENCE)")

    # Требовать ли наличие exp в входящем токене. false (по умолчанию) — допускаются
    # бессрочные токены без exp; если exp есть, он всё равно проверяется.
    jwt_require_exp: bool = Field(default=False, description="Обязателен ли claim exp (env: JWT_REQUIRE_EXP)")
    jwt_leeway_s: int = Field(default=60, ge=0, le=3600, description="Допуск при проверке exp/iat, сек (env: JWT_LEEWAY_S)")

    @field_validator("jwt_issuer", "jwt_audience", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v: object) -> object:
        """Пустая строка в env (JWT_ISSUER=) = «не проверять», как и None."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    # ------------------------------ Knowledge base --------------------------
    kb_root: Path = Path("/app/knowledge_base")
    # «только общие json» — файлы из подпапок вида ".../Общий json/*.json"
    common_dir_names: list[str] = Field(default_factory=lambda: ["Общий json"])

    # --------------------------------- Ollama -------------------------------
    ollama_base_url: str = "http://ollama:11435/"
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768
    request_timeout_s: float = 120.0
    max_retries: int = 4
    retry_backoff_base_s: float = 0.5
    retry_max_backoff_s: float = 20.0

    # ------------------------------- n8n (news_analyzer) --------------------
    # БАЗОВЫЙ URL n8n из env (в docker-compose это http://n8n:5678/).
    n8n_base_url: str = Field(
        default="http://n8n:5678/",
        description="Базовый адрес n8n (env: N8N_BASE_URL)",
    )
    # ПУТЬ к вебхуку анализа новостей — тоже вынесен в env, меняется без кода.
    n8n_news_webhook_path: str = Field(
        default="/webhook/news_analizer",
        description="Путь вебхука n8n для анализа новостей (env: N8N_NEWS_WEBHOOK_PATH)",
    )
    n8n_request_timeout_s: float = Field(
        default=30.0, gt=0, description="Таймаут запроса к вебхуку n8n, сек (env: N8N_REQUEST_TIMEOUT_S)"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def n8n_webhook_url(self) -> str:
        """Полный URL вебхука = base (env N8N_BASE_URL) + путь (env N8N_NEWS_WEBHOOK_PATH)."""
        return self.n8n_base_url.rstrip("/") + "/" + self.n8n_news_webhook_path.lstrip("/")

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

    @field_validator("common_dir_names", mode="before")
    @classmethod
    def _split_comma_lists(cls, v: object) -> object:
        """Списки из env: либо JSON ("["a","b"]"), либо строка через запятую ("a,b")."""
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                try:
                    import json

                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return [str(x).strip() for x in parsed if str(x).strip()]
                except ValueError:
                    pass  # невалидный JSON (например, оборванный) — treat as raw string
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
