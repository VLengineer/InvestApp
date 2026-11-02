"""Настройки приложения (по подобию существующего RAG-модуля)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    # --- PostgreSQL (pgvector) ---
    db_host: str = os.getenv("DB_HOST", "localhost")
    db_port: int = int(os.getenv("DB_PORT", "5432"))
    db_name: str = os.getenv("DB_NAME", "postgres")
    db_user: str = os.getenv("DB_USER", "postgres")
    db_password: str = os.getenv("DB_PASSWORD", "postgres")

    # --- Ollama (эмбеддинги) ---
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    embedding_model: str = os.getenv(
        "EMBEDDING_MODEL", "hf.co/unsloth/embeddinggemma-2-GGUF:UD-Q6_K_XL"
    )
    embedding_dim: int = int(os.getenv("EMBEDDING_DIM", "768"))

    # --- Путь к файлу профилей компаний ---
    company_profiles_json: str = os.getenv(
        "COMPANY_PROFILES_JSON",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "company_profiles", "cp.json"),
    )

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
