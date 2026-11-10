"""Параметры для оркестратора."""
from dataclasses import dataclass
from typing import List, Optional

from components.data_provider.params import DataProviderParams


@dataclass
class OrchestratorParams:
    """Параметры для оркестратора."""
    data_provider_params: List[DataProviderParams]
    batch_size: int = 100  # Размер батча для сохранения в БД
