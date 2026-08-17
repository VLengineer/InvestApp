"""Database Provider interfaces and implementations."""

from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID
import sqlite3
import json
from datetime import datetime
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
            
        Raises:
            NotImplementedError: This provider is not yet implemented.
        """
        raise NotImplementedError(
            "SQLite embedding provider is not implemented. "
            "Use GPTunnelEmbedding or OllamaEmbedding instead."
        )


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
            
        Raises:
            NotImplementedError: This provider is not yet implemented.
        """
        raise NotImplementedError(
            "SQLite vector DB provider is not implemented. "
            "Use FAISSVectorDB instead."
        )


class SQLiteDocumentsDBProvider(DocumentsDataBaseProvider):
    """SQLite-based documents database provider."""

    def __init__(self, db_path: str = ":memory:"):
        """Initialize documents DB provider.
        
        Args:
            db_path: Path to SQLite database file. Use ":memory:" for in-memory DB.
        """
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._init_schema()

    def _init_schema(self):
        """Initialize database schema."""
        cursor = self._conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                metadata TEXT
            )
        """)
        self._conn.commit()

    def get_documents(self, ids: List[UUID]) -> List[str]:
        """Retrieve documents by IDs.
        
        Args:
            ids: List of document UUIDs.
            
        Returns:
            List of document texts.
        """
        if not ids:
            return []
        
        cursor = self._conn.cursor()
        placeholders = ",".join("?" * len(ids))
        id_strings = [str(doc_id) for doc_id in ids]
        cursor.execute(f"SELECT content FROM documents WHERE id IN ({placeholders})", id_strings)
        
        return [row[0] for row in cursor.fetchall()]


class SQLiteDatabaseProvider(DataBaseProvider):
    """SQLite database provider for storing news analysis."""

    def __init__(self, db_path: str = ":memory:"):
        """Initialize SQLite database provider.
        
        Args:
            db_path: Path to SQLite database file. Use ":memory:" for in-memory DB.
        """
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._init_schema()

    def _init_schema(self):
        """Initialize database schema for news analysis storage."""
        cursor = self._conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS news_analysis (
                id TEXT PRIMARY KEY,
                title TEXT,
                body TEXT,
                source TEXT,
                published_at TEXT,
                url TEXT,
                classification TEXT,
                analytics TEXT,
                market_sentiment REAL,
                volatility_impact REAL,
                volume_impact REAL,
                sector_impact REAL,
                short_term_effect REAL,
                medium_term_effect REAL,
                confidence_score REAL,
                created_at TEXT
            )
        """)
        self._conn.commit()

    def add_in_db(self, item: NewsAnalysisItem, tf: Timeframe) -> bool:
        """Add news analysis item to database.
        
        Args:
            item: News analysis item to store.
            tf: Associated timeframe.
            
        Returns:
            True if successful.
        """
        try:
            cursor = self._conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO news_analysis 
                (id, title, body, source, published_at, url, classification, analytics,
                 market_sentiment, volatility_impact, volume_impact, sector_impact,
                 short_term_effect, medium_term_effect, confidence_score, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(item.news.id),
                item.news.title,
                item.news.body,
                item.news.source,
                item.news.published_at.isoformat(),
                item.news.url,
                item.classification,
                item.analytics,
                item.impact_scores.market_sentiment,
                item.impact_scores.volatility_impact,
                item.impact_scores.volume_impact,
                item.impact_scores.sector_impact,
                item.impact_scores.short_term_effect,
                item.impact_scores.medium_term_effect,
                item.impact_scores.confidence_score,
                datetime.now().isoformat()
            ))
            self._conn.commit()
            return True
        except Exception:
            self._conn.rollback()
            return False

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
