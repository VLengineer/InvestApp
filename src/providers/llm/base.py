"""LLM Provider interfaces and implementations."""

from abc import ABC, abstractmethod
from typing import List


class LLMProvider(ABC):
    """Interface for LLM providers."""

    @abstractmethod
    def generate(self, prompt: str, model: str) -> str:
        """Generate text from a prompt.
        
        Args:
            prompt: The input prompt string.
            model: The model identifier to use.
            
        Returns:
            Generated text response.
        """
        pass


class GPTunnelProvider(LLMProvider):
    """GPTunnel aggregator implementation of LLMProvider."""

    def __init__(self, api_url: str, api_key: str, default_model: str):
        """Initialize GPTunnel provider.
        
        Args:
            api_url: Base API URL for GPTunnel.
            api_key: API key for authentication.
            default_model: Default model to use for generation.
        """
        self.api_url = api_url
        self.api_key = api_key
        self.default_model = default_model

    def generate(self, prompt: str, model: str = None) -> str:
        """Generate text using GPTunnel API.
        
        Args:
            prompt: The input prompt string.
            model: Optional model override, uses default if not provided.
            
        Returns:
            Generated text response.
        """
        pass
