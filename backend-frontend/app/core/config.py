"""Конфигурация backend-frontend (12-Factor): всё только из переменных окружения.

Повторяет паттерн scheduler_service/app/core/config.py и python_test/app/core/config.py:
pydantic-settings + lru_cache, секреты никогда не хранятся в коде
(в репозитории только .env.example).

Подключение к БД собирается из POSTGRES_* (общая база vectordb проекта),
но можно переопределить одной строкой DATABASE_URL.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend-frontend/.env — независимо от CWD процесса
# (app/core/config.py -> parents[0]=core, [1]=app, [2]=backend-frontend|/app).
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ----------------------------- Приложение ------------------------------
    app_name: str = "backend-frontend"
    app_version: str = "1.0.0"
    environment: str = Field(default="development", pattern="^(development|staging|production|test)$")
    log_level: str = Field(default="INFO")
    port: int = Field(default=8300, description="Порт uvicorn внутри контейнера (env: PORT)")

    # -------------------------------- PostgreSQL ----------------------------
    # Совпадает с остальными сервисами проекта (общая база vectordb).
    database_url: str | None = Field(default=None, description="Готовый DSN (env: DATABASE_URL), имеет приоритет")
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "vectordb"
    postgres_user: str = Field(min_length=1)
    postgres_password: str = Field(min_length=1)
    db_pool_min_size: int = 1
    # Небольшой пул: LISTEN-соединение держится долго, REST-запросы — короткие.
    db_pool_max_size: int = 5

    # ---------------------------------- CORS ----------------------------------
    # Разрешённые origin'ы браузера (через запятую). Dev-фронт Vite живёт на 5173;
    # "*" по умолчанию: эндпоинты только для чтения, авторизации на фронте нет.
    cors_allow_origins: str = Field(
        default="*",
        description="Список origin' через запятую или '*' (env: CORS_ALLOW_ORIGINS)",
    )

    # ------------------------------- Real-time --------------------------------
    ws_poll_interval_s: float = Field(
        default=5.0, gt=0, le=60,
        description="Резервный период опроса БД (LISTEN/NOTIFY плюс polling), сек",
    )

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        return v.upper()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dsn(self) -> str:
        """Asyncpg-DSN: готовый DATABASE_URL или сборка из POSTGRES_*."""
        if self.database_url:
            url = self.database_url.strip()
            if url.startswith("postgresql+asyncpg://"):
                url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
            return url
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
