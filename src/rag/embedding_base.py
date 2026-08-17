"""
Abstract base class for embedding providers.

Implements the Strategy pattern for different embedding backends.
"""

from abc import ABC, abstractmethod
from typing import List
import numpy as np


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    @abstractmethod
    def embed(self, texts: List[str]) -> np.ndarray:
        """
        Generate embeddings for a list of texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            numpy array of shape (n_texts, embedding_dim)
        """
        pass

    @abstractmethod
    def get_embedding_dim(self) -> int:
        """
        Get the dimension of the embeddings produced by this provider.

        Returns:
            Integer dimension of embeddings.
        """
        pass
