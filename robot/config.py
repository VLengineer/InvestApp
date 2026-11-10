"""Конфигурация приложения."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Загрузка .env из директории скрипта
load_dotenv(Path(__file__).parent / ".env")


class Config:
    """Централизованная конфигурация."""
    
    # TInvest API
    TINVEST_TOKEN: str = os.getenv("TINVEST_TOKEN", "")
    BASE_URL: str = "https://invest-public-api.tbank.ru/rest"
    
    # PostgreSQL
    DATABASE_URL: str = os.getenv("DATABASE_URL") or (
        f"postgresql://{os.getenv('POSTGRES_USER', 'change_me_user')}"
        f":{os.getenv('POSTGRES_PASSWORD', 'change_me_strong_password')}"
        f"@{os.getenv('POSTGRES_HOST', 'localhost')}"
        f":{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB', 'vectordb')}"
    )
    
    # HTTP клиент
    HTTP_TIMEOUT: float = 60.0
    HTTP_CONNECT_TIMEOUT: float = 30.0
    MAX_RETRIES: int = 3
    
    # Параллелизм
    MAX_CONCURRENT_REQUESTS: int = 5
