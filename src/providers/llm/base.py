"""LLM Provider interface."""

from abc import ABC, abstractmethod


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
