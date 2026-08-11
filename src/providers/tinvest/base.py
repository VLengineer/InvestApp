"""T-Invest Provider interface and implementation."""

from abc import ABC, abstractmethod
from typing import Dict, Any

from src.domain.models import Timeframe


class TinvestProvider(ABC):
    """Interface for T-Invest API provider."""

    @abstractmethod
    def get_timeframe(self) -> Timeframe:
        """Get market timeframe data.
        
        Returns:
            Timeframe object with asset and candles.
        """
        pass

    @abstractmethod
    def get_news(self) -> Dict[str, Any]:
        """Get news data from T-Invest.
        
        Returns:
            JSON-like dictionary with news data.
        """
        pass


class TinvestProviderImpl(TinvestProvider):
    """T-Invest API implementation."""

    def __init__(self, api_key: str, sandbox: bool = False):
        """Initialize T-Invest provider.
        
        Args:
            api_key: T-Invest API key.
            sandbox: Whether to use sandbox mode.
        """
        self.api_key = api_key
        self.sandbox = sandbox

    def get_timeframe(self) -> Timeframe:
        """Get market timeframe data.
        
        Returns:
            Timeframe object with asset and candles.
        """
        pass

    def get_news(self) -> Dict[str, Any]:
        """Get news data from T-Invest.
        
        Returns:
            JSON-like dictionary with news data.
        """
        pass
