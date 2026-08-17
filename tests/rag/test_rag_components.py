"""
Tests for RAG components.
"""

import pytest
from uuid import uuid4
import numpy as np
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from rag.embedding_base import EmbeddingProvider
from rag.document_db_base import DocumentsDataBaseProvider, DocumentRecord
from rag.vector_db_faiss import FAISSVectorDB
from rag.rag_provider import RAGProvider


class MockEmbedding(EmbeddingProvider):
    """Mock embedding provider for testing."""
    
    def __init__(self, embedding_dim: int = 128):
        self._embedding_dim = embedding_dim
    
    def embed(self, texts: list) -> np.ndarray:
        """Generate deterministic mock embeddings based on text content."""
        embeddings = []
        for text in texts:
            # Create a deterministic embedding based on text hash
            np.random.seed(hash(text) % (2**32))
            embedding = np.random.randn(self._embedding_dim).astype(np.float32)
            # Normalize
            embedding = embedding / np.linalg.norm(embedding)
            embeddings.append(embedding)
        return np.array(embeddings)
    
    def get_embedding_dim(self) -> int:
        return self._embedding_dim


class MockDocumentDB(DocumentsDataBaseProvider):
    """Mock document database for testing."""
    
    def __init__(self):
        self._documents = {}
    
    def add_document(self, doc_id, content: str, metadata=None) -> bool:
        self._documents[str(doc_id)] = {"content": content, "metadata": metadata}
        return True
    
    def add_documents(self, documents: list) -> bool:
        for doc in documents:
            self._documents[str(doc.id)] = {"content": doc.content, "metadata": doc.metadata}
        return True
    
    def get_document(self, doc_id):
        doc = self._documents.get(str(doc_id))
        return doc["content"] if doc else None
    
    def get_documents(self, ids: list) -> list:
        return [
            self._documents[str(doc_id)]["content"]
            for doc_id in ids
            if str(doc_id) in self._documents
        ]
    
    def remove_document(self, doc_id) -> bool:
        if str(doc_id) in self._documents:
            del self._documents[str(doc_id)]
            return True
        return False
    
    def remove_documents(self, ids: list) -> bool:
        for doc_id in ids:
            self.remove_document(doc_id)
        return True
    
    def exists(self, doc_id) -> bool:
        return str(doc_id) in self._documents


class TestEmbeddingBase:
    """Tests for EmbeddingProvider abstract class."""
    
    def test_abstract_class_cannot_be_instantiated(self):
        """Test that abstract class cannot be instantiated directly."""
        with pytest.raises(TypeError):
            EmbeddingProvider()
    
    def test_mock_embedding_implementation(self):
        """Test mock embedding implementation."""
        embedding = MockEmbedding(embedding_dim=64)
        
        texts = ["hello", "world", "test"]
        result = embedding.embed(texts)
        
        assert result.shape == (3, 64)
        assert isinstance(result, np.ndarray)
        assert result.dtype == np.float32


class TestDocumentDBBase:
    """Tests for DocumentsDataBaseProvider abstract class."""
    
    def test_abstract_class_cannot_be_instantiated(self):
        """Test that abstract class cannot be instantiated directly."""
        with pytest.raises(TypeError):
            DocumentsDataBaseProvider()
    
    def test_mock_document_db_implementation(self):
        """Test mock document DB implementation."""
        db = MockDocumentDB()
        
        doc_id = uuid4()
        content = "Test document content"
        metadata = {"source": "test"}
        
        # Test add
        assert db.add_document(doc_id, content, metadata)
        assert db.exists(doc_id)
        
        # Test get
        assert db.get_document(doc_id) == content
        
        # Test get multiple
        doc_id2 = uuid4()
        db.add_document(doc_id2, "Another document")
        results = db.get_documents([doc_id, doc_id2])
        assert len(results) == 2
        
        # Test remove
        assert db.remove_document(doc_id)
        assert not db.exists(doc_id)


class TestSQLiteDocumentsDB:
    """Tests for SQLite document database."""
    
    def test_sqlite_in_memory(self):
        """Test SQLite DB with in-memory storage."""
        from rag.document_db_sqlite import SQLiteDocumentsDB
        
        db = SQLiteDocumentsDB(":memory:")
        
        doc_id = uuid4()
        content = "Test content"
        metadata = {"key": "value"}
        
        # Test add
        assert db.add_document(doc_id, content, metadata)
        assert db.exists(doc_id)
        
        # Test get
        assert db.get_document(doc_id) == content
        
        # Test get multiple
        doc_id2 = uuid4()
        db.add_document(doc_id2, "Another content")
        results = db.get_documents([doc_id, doc_id2])
        assert len(results) == 2
        
        # Test remove
        assert db.remove_document(doc_id)
        assert not db.exists(doc_id)
        
        db.close()
    
    def test_sqlite_batch_operations(self):
        """Test batch operations in SQLite DB."""
        from rag.document_db_sqlite import SQLiteDocumentsDB
        
        db = SQLiteDocumentsDB(":memory:")
        
        docs = [
            DocumentRecord(id=uuid4(), content=f"Doc {i}", metadata={"index": i})
            for i in range(5)
        ]
        
        assert db.add_documents(docs)
        
        ids = [doc.id for doc in docs]
        results = db.get_documents(ids)
        assert len(results) == 5
        
        db.close()


class TestFAISSVectorDB:
    """Tests for FAISS vector database."""
    
    def test_add_and_search(self):
        """Test adding vectors and searching."""
        embedding = MockEmbedding(embedding_dim=128)
        vdb = FAISSVectorDB(embedding)
        
        # Add documents
        doc_ids = [uuid4() for _ in range(10)]
        texts = [f"Document {i}" for i in range(10)]
        vectors = embedding.embed(texts)
        
        assert vdb.add_vectors(doc_ids, vectors)
        assert vdb.count() == 10
        
        # Search
        query_texts = ["Document 0"]
        query_vectors = embedding.embed(query_texts)
        
        found_ids, distances = vdb.search(query_vectors, k=3)
        
        assert len(found_ids) == 1
        assert len(found_ids[0]) == 3
        assert len(distances[0]) == 3
        
        # First result should be the most similar (document 0)
        assert found_ids[0][0] == doc_ids[0]
    
    def test_get_vector_ids(self):
        """Test get_vector_ids method."""
        embedding = MockEmbedding(embedding_dim=128)
        vdb = FAISSVectorDB(embedding)
        
        doc_ids = [uuid4() for _ in range(5)]
        texts = [f"Test {i}" for i in range(5)]
        vectors = embedding.embed(texts)
        
        vdb.add_vectors(doc_ids, vectors)
        
        query_vectors = embedding.embed(["Test 0"])
        result_ids = vdb.get_vector_ids(query_vectors, k=2)
        
        assert len(result_ids) == 2
        assert result_ids[0] == doc_ids[0]
    
    def test_remove_vector(self):
        """Test removing vectors by UUID."""
        embedding = MockEmbedding(embedding_dim=128)
        vdb = FAISSVectorDB(embedding)
        
        doc_ids = [uuid4() for _ in range(5)]
        texts = [f"Doc {i}" for i in range(5)]
        vectors = embedding.embed(texts)
        
        vdb.add_vectors(doc_ids, vectors)
        assert vdb.count() == 5
        
        # Remove one
        assert vdb.remove_by_uuid(doc_ids[0])
        assert vdb.count() == 4
        
        # Verify it's gone
        query_vectors = embedding.embed(["Doc 0"])
        found_ids, _ = vdb.search(query_vectors, k=5)
        assert doc_ids[0] not in found_ids[0]
    
    def test_remove_multiple_vectors(self):
        """Test removing multiple vectors."""
        embedding = MockEmbedding(embedding_dim=128)
        vdb = FAISSVectorDB(embedding)
        
        doc_ids = [uuid4() for _ in range(5)]
        texts = [f"Doc {i}" for i in range(5)]
        vectors = embedding.embed(texts)
        
        vdb.add_vectors(doc_ids, vectors)
        
        # Remove multiple
        assert vdb.remove_by_uuids([doc_ids[0], doc_ids[1]])
        assert vdb.count() == 3
    
    def test_clear(self):
        """Test clearing the index."""
        embedding = MockEmbedding(embedding_dim=128)
        vdb = FAISSVectorDB(embedding)
        
        doc_ids = [uuid4() for _ in range(5)]
        texts = [f"Doc {i}" for i in range(5)]
        vectors = embedding.embed(texts)
        
        vdb.add_vectors(doc_ids, vectors)
        assert vdb.count() == 5
        
        vdb.clear()
        assert vdb.count() == 0
    
    def test_empty_search(self):
        """Test searching empty index."""
        embedding = MockEmbedding(embedding_dim=128)
        vdb = FAISSVectorDB(embedding)
        
        query_vectors = embedding.embed(["test"])
        found_ids, distances = vdb.search(query_vectors, k=5)
        
        assert found_ids == [[]]
        assert distances == [[]]


class TestRAGProvider:
    """Tests for RAGProvider."""
    
    def test_add_and_retrieve(self):
        """Test adding documents and retrieving them."""
        embedding = MockEmbedding(embedding_dim=128)
        vdb = FAISSVectorDB(embedding)
        ddb = MockDocumentDB()
        
        rag = RAGProvider(embedding, vdb, ddb)
        
        doc_id = uuid4()
        content = "This is a test document about machine learning"
        
        assert rag.add_document(doc_id, content)
        assert rag.count() == 1
        
        # Retrieve by query
        results = rag.get_documents(["machine learning"], k=1)
        assert len(results) == 1
        assert results[0] == content
    
    def test_add_multiple_documents(self):
        """Test adding multiple documents at once."""
        embedding = MockEmbedding(embedding_dim=128)
        vdb = FAISSVectorDB(embedding)
        ddb = MockDocumentDB()
        
        rag = RAGProvider(embedding, vdb, ddb)
        
        documents = [
            (uuid4(), f"Document {i} about topic {i}", {"topic": i})
            for i in range(5)
        ]
        
        assert rag.add_documents(documents)
        assert rag.count() == 5
    
    def test_remove_documents(self):
        """Test removing documents."""
        embedding = MockEmbedding(embedding_dim=128)
        vdb = FAISSVectorDB(embedding)
        ddb = MockDocumentDB()
        
        rag = RAGProvider(embedding, vdb, ddb)
        
        doc_ids = [uuid4() for _ in range(5)]
        documents = [(doc_id, f"Content {i}", None) for i, doc_id in enumerate(doc_ids)]
        
        rag.add_documents(documents)
        assert rag.count() == 5
        
        # Remove some
        assert rag.remove_documents([doc_ids[0], doc_ids[1]])
        assert rag.count() == 3
        
        # Verify by checking document DB directly (not via search which uses similarity)
        remaining_docs = ddb.get_documents(doc_ids)
        # Only 3 documents should remain (indices 2, 3, 4)
        assert len(remaining_docs) == 3
    
    def test_search_with_details(self):
        """Test search method with full details."""
        embedding = MockEmbedding(embedding_dim=128)
        vdb = FAISSVectorDB(embedding)
        ddb = MockDocumentDB()
        
        rag = RAGProvider(embedding, vdb, ddb)
        
        doc_id = uuid4()
        content = "Test document content"
        rag.add_document(doc_id, content)
        
        doc_ids, distances, contents = rag.search(["test"], k=1)
        
        assert len(doc_ids) == 1
        assert len(distances) == 1
        assert len(contents) == 1
        assert doc_ids[0][0] == doc_id
        assert contents[0][0] == content
    
    def test_get_documents_by_ids(self):
        """Test getting documents by their IDs."""
        embedding = MockEmbedding(embedding_dim=128)
        vdb = FAISSVectorDB(embedding)
        ddb = MockDocumentDB()
        
        rag = RAGProvider(embedding, vdb, ddb)
        
        doc_ids = [uuid4() for _ in range(3)]
        documents = [(doc_id, f"Content {i}", None) for i, doc_id in enumerate(doc_ids)]
        
        rag.add_documents(documents)
        
        results = rag.get_documents_by_ids([doc_ids[0], doc_ids[2]])
        assert len(results) == 2
    
    def test_empty_queries(self):
        """Test handling of empty queries."""
        embedding = MockEmbedding(embedding_dim=128)
        vdb = FAISSVectorDB(embedding)
        ddb = MockDocumentDB()
        
        rag = RAGProvider(embedding, vdb, ddb)
        
        assert rag.get_documents([]) == []
        doc_ids, distances, contents = rag.search([], k=5)
        assert doc_ids == []
        assert distances == []
        assert contents == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
