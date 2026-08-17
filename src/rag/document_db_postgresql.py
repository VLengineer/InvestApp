"""
PostgreSQL document database implementation.

Stores documents with metadata in a PostgreSQL database.
"""

import os
import json
from typing import List, Optional, Dict, Any
from uuid import UUID

try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    psycopg2 = None

from .document_db_base import DocumentsDataBaseProvider, DocumentRecord


class PostgreSQLDocumentsDB(DocumentsDataBaseProvider):
    """PostgreSQL-based document database provider."""

    def __init__(
        self,
        host: str = None,
        port: int = None,
        dbname: str = None,
        user: str = None,
        password: str = None
    ):
        """
        Initialize PostgreSQL document database.

        Args:
            host: Database host. Defaults to POSTGRES_HOST env var.
            port: Database port. Defaults to POSTGRES_PORT env var.
            dbname: Database name. Defaults to POSTGRES_DB env var.
            user: Database user. Defaults to POSTGRES_USER env var.
            password: Database password. Defaults to POSTGRES_PASSWORD env var.
        """
        if psycopg2 is None:
            raise ImportError("psycopg2 is required for PostgreSQL support. Install with: pip install psycopg2-binary")

        self.host = host or os.getenv("POSTGRES_HOST", "localhost")
        self.port = int(port or os.getenv("POSTGRES_PORT", 5432))
        self.dbname = dbname or os.getenv("POSTGRES_DB", "rag_db")
        self.user = user or os.getenv("POSTGRES_USER", "postgres")
        self.password = password or os.getenv("POSTGRES_PASSWORD", "postgres")
        
        self._conn = None
        self._init_schema()

    def _get_connection(self):
        """Get or create database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                dbname=self.dbname,
                user=self.user,
                password=self.password
            )
        return self._conn

    def _init_schema(self):
        """Initialize database schema."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id UUID PRIMARY KEY,
                content TEXT NOT NULL,
                metadata JSONB
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_id ON documents(id)")
        conn.commit()
        cursor.close()

    def add_document(self, doc_id: UUID, content: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Add a single document to the database."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO documents (id, content, metadata) 
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET content = EXCLUDED.content, metadata = EXCLUDED.metadata
                """,
                (doc_id, content, json.dumps(metadata) if metadata else None)
            )
            conn.commit()
            cursor.close()
            return True
        except Exception:
            conn.rollback()
            return False

    def add_documents(self, documents: List[DocumentRecord]) -> bool:
        """Add multiple documents to the database."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            rows = [
                (doc.id, doc.content, json.dumps(doc.metadata) if doc.metadata else None)
                for doc in documents
            ]
            
            execute_values(
                cursor,
                """
                INSERT INTO documents (id, content, metadata) 
                VALUES %s
                ON CONFLICT (id) DO UPDATE SET content = EXCLUDED.content, metadata = EXCLUDED.metadata
                """,
                rows
            )
            conn.commit()
            cursor.close()
            return True
        except Exception:
            conn.rollback()
            return False

    def get_document(self, doc_id: UUID) -> Optional[str]:
        """Get a document by its ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT content FROM documents WHERE id = %s", (doc_id,))
        row = cursor.fetchone()
        cursor.close()
        return row[0] if row else None

    def get_documents(self, ids: List[UUID]) -> List[str]:
        """Get multiple documents by their IDs."""
        if not ids:
            return []
        
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT content FROM documents WHERE id = ANY(%s)", (ids,))
        rows = cursor.fetchall()
        cursor.close()
        
        return [row[0] for row in rows]

    def remove_document(self, doc_id: UUID) -> bool:
        """Remove a document from the database."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
            conn.commit()
            result = cursor.rowcount > 0
            cursor.close()
            return result
        except Exception:
            conn.rollback()
            return False

    def remove_documents(self, ids: List[UUID]) -> bool:
        """Remove multiple documents from the database."""
        if not ids:
            return True
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM documents WHERE id = ANY(%s)", (ids,))
            conn.commit()
            cursor.close()
            return True
        except Exception:
            conn.rollback()
            return False

    def exists(self, doc_id: UUID) -> bool:
        """Check if a document exists in the database."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM documents WHERE id = %s", (doc_id,))
        result = cursor.fetchone() is not None
        cursor.close()
        return result

    def close(self):
        """Close the database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None

    def __del__(self):
        """Destructor to ensure connection is closed."""
        self.close()
