"""
SQLite document database implementation.

Stores documents with metadata in a SQLite database.
"""

import sqlite3
import json
from typing import List, Optional, Dict, Any
from uuid import UUID
from pathlib import Path

from .document_db_base import DocumentsDataBaseProvider, DocumentRecord


class SQLiteDocumentsDB(DocumentsDataBaseProvider):
    """SQLite-based document database provider."""

    def __init__(self, db_path: str = ":memory:"):
        """
        Initialize SQLite document database.

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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_id ON documents(id)")
        self._conn.commit()

    def add_document(self, doc_id: UUID, content: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Add a single document to the database."""
        try:
            cursor = self._conn.cursor()
            metadata_json = json.dumps(metadata) if metadata else None
            cursor.execute(
                "INSERT OR REPLACE INTO documents (id, content, metadata) VALUES (?, ?, ?)",
                (str(doc_id), content, metadata_json)
            )
            self._conn.commit()
            return True
        except Exception:
            self._conn.rollback()
            return False

    def add_documents(self, documents: List[DocumentRecord]) -> bool:
        """Add multiple documents to the database."""
        try:
            cursor = self._conn.cursor()
            rows = []
            for doc in documents:
                metadata_json = json.dumps(doc.metadata) if doc.metadata else None
                rows.append((str(doc.id), doc.content, metadata_json))
            
            cursor.executemany(
                "INSERT OR REPLACE INTO documents (id, content, metadata) VALUES (?, ?, ?)",
                rows
            )
            self._conn.commit()
            return True
        except Exception:
            self._conn.rollback()
            return False

    def get_document(self, doc_id: UUID) -> Optional[str]:
        """Get a document by its ID."""
        cursor = self._conn.cursor()
        cursor.execute("SELECT content FROM documents WHERE id = ?", (str(doc_id),))
        row = cursor.fetchone()
        return row[0] if row else None

    def get_documents(self, ids: List[UUID]) -> List[str]:
        """Get multiple documents by their IDs."""
        if not ids:
            return []
        
        cursor = self._conn.cursor()
        placeholders = ",".join("?" * len(ids))
        id_strings = [str(doc_id) for doc_id in ids]
        cursor.execute(f"SELECT content FROM documents WHERE id IN ({placeholders})", id_strings)
        
        return [row[0] for row in cursor.fetchall()]

    def remove_document(self, doc_id: UUID) -> bool:
        """Remove a document from the database."""
        try:
            cursor = self._conn.cursor()
            cursor.execute("DELETE FROM documents WHERE id = ?", (str(doc_id),))
            self._conn.commit()
            return cursor.rowcount > 0
        except Exception:
            self._conn.rollback()
            return False

    def remove_documents(self, ids: List[UUID]) -> bool:
        """Remove multiple documents from the database."""
        if not ids:
            return True
        
        try:
            cursor = self._conn.cursor()
            placeholders = ",".join("?" * len(ids))
            id_strings = [str(doc_id) for doc_id in ids]
            cursor.execute(f"DELETE FROM documents WHERE id IN ({placeholders})", id_strings)
            self._conn.commit()
            return True
        except Exception:
            self._conn.rollback()
            return False

    def exists(self, doc_id: UUID) -> bool:
        """Check if a document exists in the database."""
        cursor = self._conn.cursor()
        cursor.execute("SELECT 1 FROM documents WHERE id = ?", (str(doc_id),))
        return cursor.fetchone() is not None

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()

    def __del__(self):
        """Destructor to ensure connection is closed."""
        self.close()
