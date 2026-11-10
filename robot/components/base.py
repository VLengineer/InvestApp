"""Базовый класс для компонентов."""
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

T = TypeVar('T')


class BaseComponent(ABC, Generic[T]):
    """Базовый класс для всех компонентов."""
    
    @abstractmethod
    async def execute(self, params: T) -> Any:
        """Выполняет основную логику компонента."""
        pass
    
    async def __call__(self, params: T) -> Any:
        """Позволяет вызывать компонент как функцию."""
        return await self.execute(params)
