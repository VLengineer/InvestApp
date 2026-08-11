"""Factory for creating LLM provider instances."""

from typing import Dict, Type

from src.config.settings import Config
from src.providers.llm.base import LLMProvider
from src.providers.llm.gptunnel import GPTunnelProvider


class LLMProviderFactory:
    """Factory for creating LLM provider instances based on configuration."""

    _providers: Dict[str, Type[LLMProvider]] = {
        "gptunnel": GPTunnelProvider,
    }

    @classmethod
    def create(cls, config: Config) -> LLMProvider:
        """Create an LLM provider instance based on configuration.
        
        Args:
            config: Application configuration containing LLM settings.
            
        Returns:
            An instance of the configured LLM provider.
            
        Raises:
            ValueError: If the specified provider is not supported.
        """
        provider_name = config.llm_provider.lower()
        
        if provider_name not in cls._providers:
            supported = ", ".join(cls._providers.keys())
            raise ValueError(
                f"Unsupported LLM provider: '{provider_name}'. "
                f"Supported providers: {supported}"
            )
        
        provider_class = cls._providers[provider_name]
        
        if provider_name == "gptunnel":
            return provider_class(
                api_key=config.llm_api_key,
                default_model=config.llm_default_model,
                use_wallet_balance=config.llm_use_wallet_balance,
            )
        
        raise ValueError(f"Failed to create LLM provider: {provider_name}")

    @classmethod
    def register_provider(cls, name: str, provider_class: Type[LLMProvider]) -> None:
        """Register a custom LLM provider.
        
        Args:
            name: The name identifier for the provider.
            provider_class: The provider class to register.
        """
        cls._providers[name.lower()] = provider_class
