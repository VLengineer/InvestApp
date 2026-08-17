"""
GPTunnel embedding provider implementation.

Uses GPTunnel API for generating embeddings.
"""

import os
import requests
from typing import List
import numpy as np

from .embedding_base import EmbeddingProvider


class GPTunnelEmbedding(EmbeddingProvider):
    """GPTunnel embedding provider."""

    def __init__(self, api_key: str = None, model: str = None, api_url: str = None, embedding_dim: int = None):
        """
        Initialize GPTunnel embedding provider.

        Args:
            api_key: GPTunnel API key. Defaults to GPTUNNEL_API_KEY env var.
            model: Model name. Defaults to GPTUNNEL_EMBEDDING_MODEL env var.
            api_url: API URL. Defaults to GPTUNNEL_API_URL env var.
            embedding_dim: Dimension of embeddings. Defaults to EMBEDDING_DIM env var.
        """
        self.api_key = api_key or os.getenv("GPTUNNEL_API_KEY", "")
        self.model = model or os.getenv("GPTUNNEL_EMBEDDING_MODEL", "text-embedding-3-small")
        self.api_url = api_url or os.getenv("GPTUNNEL_API_URL", "https://api.gptunnel.ru/v1")
        self._embedding_dim = embedding_dim or int(os.getenv("EMBEDDING_DIM", "1536"))

    def embed(self, texts: List[str]) -> np.ndarray:
        """
        Generate embeddings using GPTunnel API.

        Args:
            texts: List of text strings to embed.

        Returns:
            numpy array of shape (n_texts, embedding_dim)
        """
        if not texts:
            return np.array([]).reshape(0, self.get_embedding_dim())

        url = f"{self.api_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "input": texts
        }

        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

        embeddings = [item["embedding"] for item in data["data"]]
        result = np.array(embeddings)
        
        # Cache the dimension
        if self._embedding_dim is None:
            self._embedding_dim = result.shape[1]
        
        return result

    def get_embedding_dim(self) -> int:
        """
        Get the dimension of embeddings.

        Returns:
            Integer dimension of embeddings.
        """
        return self._embedding_dim
