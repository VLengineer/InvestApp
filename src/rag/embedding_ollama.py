"""
Ollama embedding provider implementation.

Uses local Ollama server for generating embeddings.
"""

import os
import requests
from typing import List
import numpy as np

from .embedding_base import EmbeddingProvider


class OllamaEmbedding(EmbeddingProvider):
    """Ollama embedding provider."""

    def __init__(self, model: str = None, api_url: str = None, embedding_dim: int = None):
        """
        Initialize Ollama embedding provider.

        Args:
            model: Model name. Defaults to OLLAMA_EMBEDDING_MODEL env var.
            api_url: Ollama API URL. Defaults to OLLAMA_API_URL env var.
            embedding_dim: Dimension of embeddings. Defaults to EMBEDDING_DIM env var.
        """
        self.model = model or os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
        self.api_url = api_url or os.getenv("OLLAMA_API_URL", "http://localhost:11434")
        self._embedding_dim = embedding_dim or int(os.getenv("EMBEDDING_DIM", "768"))

    def embed(self, texts: List[str]) -> np.ndarray:
        """
        Generate embeddings using Ollama API.

        Args:
            texts: List of text strings to embed.

        Returns:
            numpy array of shape (n_texts, embedding_dim)
        """
        if not texts:
            return np.array([]).reshape(0, self.get_embedding_dim())

        embeddings = []
        url = f"{self.api_url}/api/embeddings"
        
        for text in texts:
            payload = {
                "model": self.model,
                "prompt": text
            }

            response = requests.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            embeddings.append(data["embedding"])

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
