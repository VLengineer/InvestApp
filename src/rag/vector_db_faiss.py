"""
FAISS vector database implementation.

Stores document vectors in memory using FAISS for efficient similarity search.
Maps vector indices to document UUIDs.
"""

from typing import List, Tuple, Optional
from uuid import UUID
import numpy as np
import faiss

from .embedding_base import EmbeddingProvider


class FAISSVectorDB:
    """FAISS-based vector database provider."""

    def __init__(self, embedding_provider: EmbeddingProvider):
        """
        Initialize FAISS vector database.

        Args:
            embedding_provider: Embedding provider to use for generating embeddings.
        """
        self.embedding_provider = embedding_provider
        self.embedding_dim = embedding_provider.get_embedding_dim()
        
        # FAISS index (L2 distance by default)
        self._index = faiss.IndexFlatL2(self.embedding_dim)
        
        # Mapping from FAISS index to document UUID
        self._id_map: List[UUID] = []
        
        # Reverse mapping from UUID to FAISS index (for removal)
        self._uuid_to_index: dict = {}

    def add_vectors(self, doc_ids: List[UUID], vectors: np.ndarray) -> bool:
        """
        Add vectors to the index.

        Args:
            doc_ids: List of document UUIDs corresponding to the vectors.
            vectors: numpy array of shape (n_vectors, embedding_dim).

        Returns:
            True if successful, False otherwise.
        """
        if len(doc_ids) != len(vectors):
            return False
        
        if len(vectors) == 0:
            return True
        
        try:
            # Ensure vectors are float32 for FAISS
            vectors = vectors.astype(np.float32)
            
            # Add vectors to FAISS index
            start_index = self._index.ntotal
            self._index.add(vectors)
            
            # Update mappings
            for i, doc_id in enumerate(doc_ids):
                faiss_index = start_index + i
                self._id_map.append(doc_id)
                self._uuid_to_index[doc_id] = faiss_index
            
            return True
        except Exception:
            return False

    def search(
        self, 
        query_vectors: np.ndarray, 
        k: int = 5
    ) -> Tuple[List[List[UUID]], List[List[float]]]:
        """
        Search for similar vectors.

        Args:
            query_vectors: numpy array of shape (n_queries, embedding_dim).
            k: Number of nearest neighbors to return.

        Returns:
            Tuple of (document_ids, distances):
            - document_ids: List of lists of UUIDs for each query
            - distances: List of lists of distances for each query
        """
        if self._index.ntotal == 0:
            n_queries = len(query_vectors) if len(query_vectors.shape) > 1 else 1
            return [[] for _ in range(n_queries)], [[] for _ in range(n_queries)]
        
        # Ensure vectors are float32 for FAISS
        query_vectors = query_vectors.astype(np.float32)
        
        # Adjust k if we have fewer vectors than requested
        k = min(k, self._index.ntotal)
        
        # Search
        distances, indices = self._index.search(query_vectors, k)
        
        # Map FAISS indices to document UUIDs
        doc_ids = []
        doc_distances = []
        
        for query_indices, query_distances in zip(indices, distances):
            ids_for_query = []
            dists_for_query = []
            
            for idx, dist in zip(query_indices, query_distances):
                if idx < len(self._id_map):
                    ids_for_query.append(self._id_map[idx])
                    dists_for_query.append(float(dist))
            
            doc_ids.append(ids_for_query)
            doc_distances.append(dists_for_query)
        
        return doc_ids, doc_distances

    def get_vector_ids(self, vectors: np.ndarray, k: int = 5) -> List[UUID]:
        """
        Get document IDs for the most similar vectors to the given query vectors.
        This matches the interface from the original schema.

        Args:
            vectors: Query vectors of shape (n_queries, embedding_dim).
            k: Number of nearest neighbors to return.

        Returns:
            List of UUIDs for the most similar documents (flattened from all queries).
        """
        doc_ids, _ = self.search(vectors, k)
        
        # Flatten the list of lists
        result = []
        for query_ids in doc_ids:
            result.extend(query_ids)
        
        return result

    def remove_by_uuid(self, doc_id: UUID) -> bool:
        """
        Remove a vector by its document UUID.

        Note: FAISS doesn't support efficient removal. This implementation
        rebuilds the index without the removed vector.

        Args:
            doc_id: Document UUID to remove.

        Returns:
            True if successful, False otherwise.
        """
        if doc_id not in self._uuid_to_index:
            return False
        
        try:
            # Get the FAISS index to remove
            faiss_idx = self._uuid_to_index[doc_id]
            
            # Get all vectors except the one to remove
            all_vectors = self._index.reconstruct_n(0, self._index.ntotal)
            
            # Create mask for vectors to keep
            keep_mask = np.ones(len(all_vectors), dtype=bool)
            keep_mask[faiss_idx] = False
            
            # Get vectors to keep
            vectors_to_keep = all_vectors[keep_mask]
            
            # Rebuild index
            self._index = faiss.IndexFlatL2(self.embedding_dim)
            self._id_map = []
            self._uuid_to_index = {}
            
            # Re-add vectors and rebuild mappings
            if len(vectors_to_keep) > 0:
                self._index.add(vectors_to_keep)
                
                # Rebuild mappings
                old_id_map = [uid for i, uid in enumerate(self._id_map) if keep_mask[i]]
                for new_idx, doc_uid in enumerate(old_id_map):
                    self._id_map.append(doc_uid)
                    self._uuid_to_index[doc_uid] = new_idx
            
            return True
        except Exception:
            return False

    def remove_by_uuids(self, doc_ids: List[UUID]) -> bool:
        """
        Remove multiple vectors by their document UUIDs.

        Args:
            doc_ids: List of document UUIDs to remove.

        Returns:
            True if successful, False otherwise.
        """
        try:
            # Get all vectors
            all_vectors = self._index.reconstruct_n(0, self._index.ntotal) if self._index.ntotal > 0 else np.array([])
            
            if len(all_vectors) == 0:
                return True
            
            # Create mask for vectors to keep
            keep_mask = np.ones(len(all_vectors), dtype=bool)
            for doc_id in doc_ids:
                if doc_id in self._uuid_to_index:
                    faiss_idx = self._uuid_to_index[doc_id]
                    if faiss_idx < len(keep_mask):
                        keep_mask[faiss_idx] = False
            
            # Get vectors to keep
            vectors_to_keep = all_vectors[keep_mask]
            
            # Rebuild index
            self._index = faiss.IndexFlatL2(self.embedding_dim)
            self._id_map = []
            self._uuid_to_index = {}
            
            # Re-add vectors and rebuild mappings
            if len(vectors_to_keep) > 0:
                self._index.add(vectors_to_keep)
                
                # Rebuild mappings
                old_id_map = [uid for i, uid in enumerate(self._id_map) if keep_mask[i]]
                for new_idx, doc_uid in enumerate(old_id_map):
                    self._id_map.append(doc_uid)
                    self._uuid_to_index[doc_uid] = new_idx
            
            return True
        except Exception:
            return False

    def count(self) -> int:
        """
        Get the number of vectors in the index.

        Returns:
            Number of vectors.
        """
        return self._index.ntotal

    def clear(self):
        """Clear all vectors from the index."""
        self._index = faiss.IndexFlatL2(self.embedding_dim)
        self._id_map = []
        self._uuid_to_index = {}
