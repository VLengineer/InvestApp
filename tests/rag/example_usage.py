"""
Example usage of RAG components.

This example demonstrates how to use the RAG provider with different
embedding strategies and document databases.
"""

import os
import sys
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from rag.embedding_ollama import OllamaEmbedding
from rag.embedding_gptunnel import GPTunnelEmbedding
from rag.document_db_sqlite import SQLiteDocumentsDB
from rag.vector_db_faiss import FAISSVectorDB
from rag.rag_provider import RAGProvider


def example_with_mock_embedding():
    """Example using mock embedding for testing."""
    from rag.document_db_base import DocumentsDataBaseProvider, DocumentRecord
    import numpy as np
    
    class MockEmbedding:
        def __init__(self, dim=128):
            self.dim = dim
        
        def embed(self, texts):
            embeddings = []
            for text in texts:
                np.random.seed(hash(text) % (2**32))
                emb = np.random.randn(self.dim).astype(np.float32)
                emb = emb / np.linalg.norm(emb)
                embeddings.append(emb)
            return np.array(embeddings)
        
        def get_embedding_dim(self):
            return self.dim
    
    # Initialize components
    embedding = MockEmbedding(dim=128)
    vdb = FAISSVectorDB(embedding)
    ddb = SQLiteDocumentsDB(":memory:")
    
    rag = RAGProvider(embedding, vdb, ddb)
    
    # Add documents
    documents = [
        (uuid4(), "Machine learning is a subset of artificial intelligence", {"topic": "AI"}),
        (uuid4(), "Python is a popular programming language for data science", {"topic": "Programming"}),
        (uuid4(), "Neural networks are inspired by biological neurons", {"topic": "AI"}),
        (uuid4(), "Database management systems store and retrieve data", {"topic": "Databases"}),
    ]
    
    print("Adding documents...")
    rag.add_documents(documents)
    print(f"Total documents: {rag.count()}")
    
    # Search
    print("\nSearching for 'artificial intelligence'...")
    results = rag.get_documents(["artificial intelligence"], k=2)
    for i, doc in enumerate(results, 1):
        print(f"  {i}. {doc}")
    
    # Search with details
    print("\nSearching with details...")
    doc_ids, distances, contents = rag.search(["python programming"], k=2)
    for i, (doc_id, dist, content) in enumerate(zip(doc_ids[0], distances[0], contents[0]), 1):
        print(f"  {i}. Distance: {dist:.4f}, Content: {content[:50]}...")
    
    # Remove documents
    print("\nRemoving first document...")
    rag.remove_document(documents[0][0])
    print(f"Remaining documents: {rag.count()}")


def example_with_ollama():
    """Example using Ollama for embeddings (requires running Ollama server)."""
    # Check if Ollama is available
    try:
        import requests
        response = requests.get("http://localhost:11434/api/tags", timeout=2)
        if response.status_code != 200:
            raise Exception("Ollama not available")
    except Exception:
        print("Ollama not available, skipping this example")
        return
    
    # Initialize with Ollama
    embedding = OllamaEmbedding(
        model=os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"),
        api_url=os.getenv("OLLAMA_API_URL", "http://localhost:11434")
    )
    
    vdb = FAISSVectorDB(embedding)
    ddb = SQLiteDocumentsDB("documents.db")  # Persistent storage
    
    rag = RAGProvider(embedding, vdb, ddb)
    
    # Add documents
    rag.add_document(
        uuid4(),
        "RAG combines retrieval and generation for better AI responses",
        {"category": "AI"}
    )
    
    # Search
    results = rag.get_documents(["retrieval augmented generation"], k=3)
    print("Search results:", results)
    
    ddb.close()


def example_with_gptunnel():
    """Example using GPTunnel for embeddings (requires API key)."""
    api_key = os.getenv("GPTUNNEL_API_KEY")
    if not api_key:
        print("GPTUNNEL_API_KEY not set, skipping this example")
        return
    
    # Initialize with GPTunnel
    embedding = GPTunnelEmbedding(
        api_key=api_key,
        model=os.getenv("GPTUNNEL_EMBEDDING_MODEL", "text-embedding-3-small"),
        api_url=os.getenv("GPTUNNEL_API_URL", "https://api.gptunnel.ru/v1")
    )
    
    vdb = FAISSVectorDB(embedding)
    ddb = SQLiteDocumentsDB(":memory:")
    
    rag = RAGProvider(embedding, vdb, ddb)
    
    # Add documents
    rag.add_document(uuid4(), "Financial markets are influenced by many factors")
    
    # Search
    results = rag.get_documents(["economy and finance"], k=5)
    print("Search results:", results)


if __name__ == "__main__":
    print("=" * 60)
    print("RAG Components Example")
    print("=" * 60)
    
    print("\n1. Example with Mock Embedding:")
    print("-" * 40)
    example_with_mock_embedding()
    
    print("\n2. Example with Ollama:")
    print("-" * 40)
    example_with_ollama()
    
    print("\n3. Example with GPTunnel:")
    print("-" * 40)
    example_with_gptunnel()
    
    print("\n" + "=" * 60)
    print("Examples completed!")
    print("=" * 60)
