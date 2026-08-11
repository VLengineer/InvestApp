"""LLM Provider interfaces and implementations."""

from abc import ABC, abstractmethod
from typing import Optional

import httpx


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

    API_URL = "https://gptunnel.ru/v1/chat/completions"

    def __init__(self, api_key: str, default_model: str = "qwen3.8", use_wallet_balance: bool = True):
        """Initialize GPTunnel provider.
        
        Args:
            api_key: API key for authentication.
            default_model: Default model to use for generation (default: qwen3.8).
            use_wallet_balance: Whether to use wallet balance for payment.
        """
        self.api_key = api_key
        self.default_model = default_model
        self.use_wallet_balance = use_wallet_balance
        self._client = httpx.Client(timeout=60.0)

    def generate(self, prompt: str, model: Optional[str] = None) -> str:
        """Generate text using GPTunnel API.
        
        Args:
            prompt: The input prompt string.
            model: Optional model override, uses default if not provided.
            
        Returns:
            Generated text response.
            
        Raises:
            RuntimeError: If the API request fails.
        """
        model_to_use = model or self.default_model
        
        headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": model_to_use,
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "useWalletBalance": self.use_wallet_balance,
        }
        
        try:
            response = self._client.post(
                self.API_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            
            # Extract the generated content from the response
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return ""
            
        except httpx.HTTPError as e:
            raise RuntimeError(f"GPTunnel API request failed: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to generate text from GPTunnel: {e}")
