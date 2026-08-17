"""
Abstract base class for document database providers.

Implements the Strategy pattern for different document storage backends.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from uuid import UUID


class DocumentRecord:
    """Represents a document with metadata."""
    
    def __init__(
        self,
        id: UUID,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.id = id
        self.content = content
        self.metadata = metadata or {}


class DocumentsDataBaseProvider(ABC):
    """Abstract base class for document database providers."""

    @abstractmethod
    def add_document(self, doc_id: UUID, content: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Add a document to the database.

        Args:
            doc_id: Unique identifier for the document.
            content: The document text content.
            metadata: Optional metadata dictionary.

        Returns:
            True if successful, False otherwise.
        """
        pass

    @abstractmethod
    def add_documents(self, documents: List[DocumentRecord]) -> bool:
        """
        Add multiple documents to the database.

        Args:
            documents: List of DocumentRecord objects.

        Returns:
            True if successful, False otherwise.
        """
        pass

    @abstractmethod
    def get_document(self, doc_id: UUID) -> Optional[str]:
        """
        Get a document by its ID.

        Args:
            doc_id: Unique identifier for the document.

        Returns:
            Document content string, or None if not found.
        """
        pass

    @abstractmethod
    def get_documents(self, ids: List[UUID]) -> List[str]:
        """
        Get multiple documents by their IDs.

        Args:
            ids: List of unique identifiers.

        Returns:
            List of document content strings. Missing documents are skipped.
        """
        pass

    @abstractmethod
    def remove_document(self, doc_id: UUID) -> bool:
        """
        Remove a document from the database.

        Args:
            doc_id: Unique identifier for the document.

        Returns:
            True if successful, False otherwise.
        """
        pass

    @abstractmethod
    def remove_documents(self, ids: List[UUID]) -> bool:
        """
        Remove multiple documents from the database.

        Args:
            ids: List of unique identifiers.

        Returns:
            True if successful, False otherwise.
        """
        pass

    @abstractmethod
    def exists(self, doc_id: UUID) -> bool:
        """
        Check if a document exists in the database.

        Args:
            doc_id: Unique identifier for the document.

        Returns:
            True if exists, False otherwise.
        """
        pass
