"""Конфигурация scheduler_service (12-Factor): всё только из переменных окружения.

Повторяет паттерн python_test/app/core/config.py: pydantic-settings + lru_cache,
секреты никогда не хранятся в коде (в репозитории только .env.example).

Подключение к БД собирается из POSTGRES_* (как в основном сервисе), но можно
переопределить одной строкой DATABASE_URL (postgresql://... или postgresql+asyncpg://...).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# scheduler_service/.env — независимо от CWD процесса
# (app/core/config.py -> parents[0]=core, [1]=app, [2]=scheduler_service|/app).
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ----------------------------- Приложение ------------------------------
    app_name: str = "scheduler-service"
    app_version: str = "1.0.0"
    environment: str = Field(default="development", pattern="^(development|staging|production|test)$")
    log_level: str = Field(default="INFO")
    port: int = Field(default=8200, description="Порт uvicorn внутри контейнера (env: PORT)")

    # ------------------------------- Безопасность ---------------------------
    # Единый JWT-секрет проекта (тот же, что у python_test): один токен на всё.
    jwt_secret_key: str = Field(min_length=32, description="HS256 секрет для проверки JWT (env: JWT_SECRET_KEY)")
    jwt_algorithm: str = "HS256"
    jwt_issuer: str | None = Field(default=None, description="Ожидаемый claim iss, если задан (env: JWT_ISSUER)")
    jwt_audience: str | None = Field(default=None, description="Ожидаемый claim aud, если задан (env: JWT_AUDIENCE)")
    jwt_require_exp: bool = Field(default=False, description="Обязателен ли claim exp (env: JWT_REQUIRE_EXP)")
    jwt_leeway_s: int = Field(default=60, ge=0, le=3600, description="Допуск при проверке exp/iat, сек")

    # Секрет для callback-эндпоинта от n8n (заголовок X-Callback-Secret).
    callback_secret: str = Field(min_length=16, description="Секрет проверки callback от n8n (env: CALLBACK_SECRET)")

    # -------------------------------- PostgreSQL ----------------------------
    # Совпадает с остальными сервисами проекта (общая база vectordb).
    database_url: str | None = Field(default=None, description="Готовый DSN (env: DATABASE_URL), имеет приоритет")
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "vectordb"
    postgres_user: str = Field(min_length=1)
    postgres_password: str = Field(min_length=1)
    db_pool_min_size: int = 1
    # Небольшой пул: воркер держит соединения долго (polling/callback), API — короткие.
    db_pool_max_size: int = 5

    # ---------------------------------- n8n ---------------------------------
    # URL вебхука запуска процесса (внутри docker-сети app_net — по имени сервиса).
    n8n_webhook_url: str = Field(
        default="http://n8n:5678/webhook/start_process",
        description="POST-вебхук n8n для старта процесса (env: N8N_WEBHOOK_URL)",
    )
    # Тестовый вебхук n8n (режим Test workflow) — используется эндпоинтом
    # POST /api/v1/scheduler/test-trigger для ручного триггера без очереди.
    n8n_test_webhook_url: str = Field(
        default="http://n8n:5678/webhook-test/start_process",
        description="POST-тестовый вебхук n8n (env: N8N_TEST_WEBHOOK_URL)",
    )
    # JWT, который n8n ожидает в Authorization: Bearer на входящем вебхуке.
    n8n_webhook_jwt_token: str = Field(
        default="",
        description="Bearer-токен для запросов к вебхуку n8n (env: N8N_WEBHOOK_JWT_TOKEN)",
    )
    n8n_request_timeout_s: float = Field(default=30.0, gt=0)

    # ------------------------------- Воркер ---------------------------------
    poll_interval_s: int = Field(default=10, ge=1, description="Период опроса таблицы tasks и статуса задачи, сек")
    idle_poll_interval_s: int = Field(default=5, ge=1, description="Пауза polling'а, когда в очереди нет waiting-задач, сек")
    inactive_check_interval_s: int = Field(default=5, ge=1, description="Пауза, пока планировщик выключен, сек")
    sleep_after_completed_s: int = Field(default=600, ge=0, description="Пауза после completed (10 мин), сек")
    sleep_after_error_s: int = Field(default=300, ge=0, description="Пауза после error (5 мин), сек")
    # Страховка от «зависшей» processing, если callback так и не пришёл (n8n упал):
    # по истечении таймаута задача помечается error, цикл берёт следующую waiting.
    task_wait_timeout_s: int = Field(default=3600, ge=60, description="Максимум ожидания callback, сек")
    heartbeat_log_every_s: int = Field(
        default=60,
        ge=0,
        description=(
            "Период INFO-сообщения «пульса» воркера (очередь пуста/планировщик выключен). "
            "0 = только DEBUG. Без него при LOG_LEVEL=INFO сервис выглядит «молчащим»."
        ),
    )

    # ---------------------- Фоновый генератор задач (producer) ----------------
    # Каждые task_generation_interval_s создаёт новую задачу со статусом 'waiting',
    # если планировщик активен и очередь не переполнена (см. max_waiting_tasks).
    task_generation_enabled: bool = Field(
        default=True,
        description="Фоновое создание задач каждые N секунд (env: TASK_GENERATION_ENABLED)",
    )
    task_generation_interval_s: int = Field(
        default=300,
        ge=1,
        description="Период создания новых waiting-задач, сек (env: TASK_GENERATION_INTERVAL_S; 300 = 5 минут)",
    )
    max_waiting_tasks: int = Field(
        default=10,
        ge=1,
        description=(
            "Максимум задач со статусом 'waiting' в очереди: пока счётчик >= этого "
            "значения, новые задачи НЕ создаются (env: MAX_WAITING_TASKS)"
        ),
    )

    @field_validator("jwt_issuer", "jwt_audience", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v: object) -> object:
        """Пустая строка в env (JWT_ISSUER=) = «не проверять», как и None."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        return v.upper()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dsn(self) -> str:
        """Asyncpg-DSN: готовый DATABASE_URL или сборка из POSTGRES_* (пароль не светится в одном поле)."""
        if self.database_url:
            # Нормализуем SQLAlchemy-стиль в asyncpg-стиль, если пришли с +asyncpg.
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
