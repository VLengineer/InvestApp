"""Configuration module for News Market Analyzer."""

import os
from typing import Optional
from dataclasses import dataclass


@dataclass
class Config:
    """Application configuration."""

    # Core
    app_name: str = "news_market_analyzer"
    log_level: str = "INFO"

    # T-Invest
    tinvest_api_key: str = ""
    tinvest_sandbox: bool = False

    # LLM (GPTunnel)
    llm_provider: str = "gptunnel"
    llm_api_url: str = "https://gptunnel.ru/v1/chat/completions"
    llm_api_key: str = ""
    llm_default_model: str = "qwen3.8"
    llm_use_wallet_balance: bool = True

    # Database
    db_provider: str = "sqlite"
    sqlite_db_path: str = "./data/news_market.db"

    # RAG
    rag_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    rag_top_k: int = 5

    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> "Config":
        """Load configuration from environment variables.
        
        Args:
            env_file: Optional path to .env file.
            
        Returns:
            Config instance populated from environment.
        """
        if env_file and os.path.exists(env_file):
            from dotenv import load_dotenv
            load_dotenv(env_file)
        elif os.path.exists(".env"):
            from dotenv import load_dotenv
            load_dotenv(".env")

        return cls(
            app_name=os.getenv("APP_NAME", cls.app_name),
            log_level=os.getenv("LOG_LEVEL", cls.log_level),
            tinvest_api_key=os.getenv("TINVEST_API_KEY", ""),
            tinvest_sandbox=os.getenv("TINVEST_SANDBOX", "false").lower() == "true",
            llm_provider=os.getenv("LLM_PROVIDER", cls.llm_provider),
            llm_api_url=os.getenv("LLM_API_URL", cls.llm_api_url),
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_default_model=os.getenv("LLM_DEFAULT_MODEL", cls.llm_default_model),
            llm_use_wallet_balance=os.getenv("LLM_USE_WALLET_BALANCE", "true").lower() == "true",
            db_provider=os.getenv("DB_PROVIDER", cls.db_provider),
            sqlite_db_path=os.getenv("SQLITE_DB_PATH", cls.sqlite_db_path),
            rag_embedding_model=os.getenv("RAG_EMBEDDING_MODEL", cls.rag_embedding_model),
            rag_top_k=int(os.getenv("RAG_TOP_K", str(cls.rag_top_k))),
        )


config = Config.from_env()
