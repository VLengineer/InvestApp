"""Database Provider interfaces and implementations."""

from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID
import numpy as np

from src.domain.models import NewsAnalysisItem, Timeframe


class EmbeddingProvider(ABC):
    """Interface for embedding providers."""

    @abstractmethod
    def embed(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings for a list of texts.
        
        Args:
            texts: List of text strings to embed.
            
        Returns:
            Numpy array of embeddings.
        """
        pass


class VectorDataBaseProvider(ABC):
    """Interface for vector database providers."""

    @abstractmethod
    def get_documents_id(self, vectors: np.ndarray) -> List[UUID]:
        """Find document IDs similar to given vectors.
        
        Args:
            vectors: Query vectors to search for.
            
        Returns:
            List of matching document UUIDs.
        """
        pass


class DocumentsDataBaseProvider(ABC):
    """Interface for documents database providers."""

    @abstractmethod
    def get_documents(self, ids: List[UUID]) -> List[str]:
        """Retrieve documents by their IDs.
        
        Args:
            ids: List of document UUIDs.
            
        Returns:
            List of document texts.
        """
        pass


class DataBaseProvider(ABC):
    """Interface for main database providers."""

    @abstractmethod
    def add_in_db(self, item: NewsAnalysisItem, tf: Timeframe) -> bool:
        """Add a news analysis item to the database.
        
        Args:
            item: The news analysis item to store.
            tf: Associated timeframe.
            
        Returns:
            True if successful, False otherwise.
        """
        pass


class SQLiteEmbeddingProvider(EmbeddingProvider):
    """SQLite-based embedding provider (placeholder)."""

    def __init__(self, model_name: str):
        """Initialize embedding provider.
        
        Args:
            model_name: Name of the embedding model to use.
        """
        self.model_name = model_name

    def embed(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings for texts.
        
        Args:
            texts: List of text strings to embed.
            
        Returns:
            Numpy array of embeddings.
        """
        pass


class SQLiteVectorDBProvider(VectorDataBaseProvider):
    """SQLite-based vector database provider (placeholder)."""

    def __init__(self, db_path: str):
        """Initialize vector DB provider.
        
        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path

    def get_documents_id(self, vectors: np.ndarray) -> List[UUID]:
        """Find similar document IDs.
        
        Args:
            vectors: Query vectors.
            
        Returns:
            List of document UUIDs.
        """
        pass


class SQLiteDocumentsDBProvider(DocumentsDataBaseProvider):
    """SQLite-based documents database provider."""

    def __init__(self, db_path: str):
        """Initialize documents DB provider.
        
        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path

    def get_documents(self, ids: List[UUID]) -> List[str]:
        """Retrieve documents by IDs.
        
        Args:
            ids: List of document UUIDs.
            
        Returns:
            List of document texts.
        """
        pass


class SQLiteDatabaseProvider(DataBaseProvider):
    """SQLite database provider for storing news analysis."""

    def __init__(self, db_path: str):
        """Initialize SQLite database provider.
        
        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path

    def add_in_db(self, item: NewsAnalysisItem, tf: Timeframe) -> bool:
        """Add news analysis item to database.
        
        Args:
            item: News analysis item to store.
            tf: Associated timeframe.
            
        Returns:
            True if successful.
        """
        pass
