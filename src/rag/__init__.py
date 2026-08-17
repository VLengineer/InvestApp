"""
RAG (Retrieval-Augmented Generation) components.

This module provides:
- Embedding strategies (GPTunnel, Ollama)
- Vector database storage (FAISS)
- Document database strategies (SQLite, PostgreSQL)
- RAG provider for document management
"""

from .embedding_base import EmbeddingProvider
from .embedding_gptunnel import GPTunnelEmbedding
from .embedding_ollama import OllamaEmbedding
from .document_db_base import DocumentsDataBaseProvider
from .document_db_sqlite import SQLiteDocumentsDB
from .document_db_postgresql import PostgreSQLDocumentsDB
from .vector_db_faiss import FAISSVectorDB
from .rag_provider import RAGProvider

__all__ = [
    "EmbeddingProvider",
    "GPTunnelEmbedding",
    "OllamaEmbedding",
    "DocumentsDataBaseProvider",
    "SQLiteDocumentsDB",
    "PostgreSQLDocumentsDB",
    "FAISSVectorDB",
    "RAGProvider",
]
