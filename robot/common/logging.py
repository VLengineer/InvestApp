"""Настройка логирования."""
import logging
import warnings
import urllib3


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Настраивает логирование и подавляет warnings."""
    # Подавляем warning о невалидном SSL-сертификате
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    warnings.filterwarnings("ignore", message="Unverified HTTPS request")
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    return logging.getLogger(__name__)
