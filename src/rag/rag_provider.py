"""
RAG Provider implementation.

Combines embedding, vector database, and document database for
Retrieval-Augmented Generation functionality.
"""

from typing import List, Optional, Dict, Any, Tuple
from uuid import UUID
import numpy as np

from .embedding_base import EmbeddingProvider
from .vector_db_faiss import FAISSVectorDB
from .document_db_base import DocumentsDataBaseProvider, DocumentRecord


class RAGProvider:
    """
    RAG (Retrieval-Augmented Generation) provider.
    
    Combines embedding generation, vector storage, and document retrieval.
    """

    def __init__(
        self,
        embedding: EmbeddingProvider,
        vdb: FAISSVectorDB,
        ddb: DocumentsDataBaseProvider
    ):
        """
        Initialize RAG provider.

        Args:
            embedding: Embedding provider for generating vectors.
            vdb: Vector database for storing and searching vectors.
            ddb: Document database for storing document content.
        """
        self.embedding = embedding
        self.vdb = vdb
        self.ddb = ddb

    def add_documents(
        self,
        documents: List[Tuple[UUID, str, Optional[Dict[str, Any]]]]
    ) -> bool:
        """
        Add documents to both vector and document databases.

        Args:
            documents: List of tuples (doc_id, content, metadata).

        Returns:
            True if all documents were added successfully, False otherwise.
        """
        if not documents:
            return True
        
        try:
            # Extract content and generate embeddings
            doc_ids = [doc[0] for doc in documents]
            contents = [doc[1] for doc in documents]
            metadata_list = [doc[2] for doc in documents]
            
            # Generate embeddings
            vectors = self.embedding.embed(contents)
            
            # Add to vector database
            vdb_success = self.vdb.add_vectors(doc_ids, vectors)
            if not vdb_success:
                return False
            
            # Add to document database
            doc_records = [
                DocumentRecord(id=doc_id, content=content, metadata=metadata)
                for doc_id, content, metadata in documents
            ]
            ddb_success = self.ddb.add_documents(doc_records)
            
            return ddb_success
        except Exception:
            return False

    def add_document(
        self,
        doc_id: UUID,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Add a single document to both databases.

        Args:
            doc_id: Unique identifier for the document.
            content: Document text content.
            metadata: Optional metadata dictionary.

        Returns:
            True if successful, False otherwise.
        """
        return self.add_documents([(doc_id, content, metadata)])

    def get_documents(self, queries: List[str], k: int = 5) -> List[str]:
        """
        Get relevant documents for given queries.

        Args:
            queries: List of query strings.
            k: Number of nearest neighbors to retrieve per query.

        Returns:
            List of document content strings for the most relevant documents.
        """
        if not queries:
            return []
        
        # Generate embeddings for queries
        query_vectors = self.embedding.embed(queries)
        
        # Search in vector database
        doc_ids, _ = self.vdb.search(query_vectors, k)
        
        # Flatten unique IDs while preserving order
        seen = set()
        unique_ids = []
        for query_ids in doc_ids:
            for doc_id in query_ids:
                if doc_id not in seen:
                    seen.add(doc_id)
                    unique_ids.append(doc_id)
        
        # Retrieve documents from document database
        if not unique_ids:
            return []
        
        return self.ddb.get_documents(unique_ids)

    def get_documents_by_ids(self, ids: List[UUID]) -> List[str]:
        """
        Get documents by their IDs.

        Args:
            ids: List of document UUIDs.

        Returns:
            List of document content strings.
        """
        return self.ddb.get_documents(ids)

    def remove_documents(self, ids: List[UUID]) -> bool:
        """
        Remove documents from both databases.

        Args:
            ids: List of document UUIDs to remove.

        Returns:
            True if successful, False otherwise.
        """
        if not ids:
            return True
        
        try:
            # Remove from vector database
            vdb_success = self.vdb.remove_by_uuids(ids)
            
            # Remove from document database
            ddb_success = self.ddb.remove_documents(ids)
            
            return vdb_success and ddb_success
        except Exception:
            return False

    def remove_document(self, doc_id: UUID) -> bool:
        """
        Remove a single document from both databases.

        Args:
            doc_id: Document UUID to remove.

        Returns:
            True if successful, False otherwise.
        """
        return self.remove_documents([doc_id])

    def search(
        self,
        queries: List[str],
        k: int = 5
    ) -> Tuple[List[List[UUID]], List[List[float]], List[List[str]]]:
        """
        Search for relevant documents with full details.

        Args:
            queries: List of query strings.
            k: Number of nearest neighbors per query.

        Returns:
            Tuple of (doc_ids, distances, contents):
            - doc_ids: List of lists of UUIDs for each query
            - distances: List of lists of distances for each query
            - contents: List of lists of document contents for each query
        """
        if not queries:
            return [], [], []
        
        # Generate embeddings for queries
        query_vectors = self.embedding.embed(queries)
        
        # Search in vector database
        doc_ids, distances = self.vdb.search(query_vectors, k)
        
        # Retrieve document contents
        contents = []
        for query_ids in doc_ids:
            query_contents = self.ddb.get_documents(query_ids)
            contents.append(query_contents)
        
        return doc_ids, distances, contents

    def count(self) -> int:
        """
        Get the number of documents in the vector database.

        Returns:
            Number of documents.
        """
        return self.vdb.count()

    def clear(self):
        """Clear all documents from both databases."""
        self.vdb.clear()
        # Note: We don't clear the document database here as it might be shared
