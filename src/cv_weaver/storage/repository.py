"""Repository layer for CVPoint CRUD operations.

Uses raw sqlite3 with dependency-injected connections.
All methods accept and return typed Pydantic models.
"""

import sqlite3
from typing import List, Optional

from cv_weaver.models.enums import GenerationLevel, Status
from cv_weaver.models.schemas import CVPoint


class CVPointRepository:
    """Typed CRUD interface over the `cv_points` SQLite table."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def insert(self, point: CVPoint) -> None:
        """Insert a new CVPoint into the database.

        Args:
            point: The canonical CVPoint to persist.
        """
        data = point.to_sqlite_dict()
        columns = ", ".join(data.keys())
        placeholders = ", ".join(f":{k}" for k in data.keys())
        sql = f"INSERT INTO cv_points ({columns}) VALUES ({placeholders})"
        with self._conn:
            self._conn.execute(sql, data)

    def get_by_id(self, point_id: str) -> Optional[CVPoint]:
        """Fetch a single CVPoint by its UUID.

        Args:
            point_id: The UUID of the CVPoint.

        Returns:
            The CVPoint if found, otherwise None.
        """
        row = self._conn.execute(
            "SELECT * FROM cv_points WHERE id = ?", (point_id,)
        ).fetchone()
        return CVPoint.from_sqlite_row(row) if row else None

    def list_by_status(self, status: Status) -> List[CVPoint]:
        """Fetch all CVPoints matching the given status.

        Args:
            status: One of draft, approved, or archived.

        Returns:
            A list of matching CVPoints.
        """
        rows = self._conn.execute(
            "SELECT * FROM cv_points WHERE status = ?", (status.value,)
        ).fetchall()
        return [CVPoint.from_sqlite_row(row) for row in rows]

    def list_by_source(self, file_id: str) -> List[CVPoint]:
        """Fetch all CVPoints derived from a specific knowledge source file.

        Args:
            file_id: The source file identifier (e.g. `01_tata-neu`).

        Returns:
            A list of matching CVPoints.
        """
        rows = self._conn.execute(
            "SELECT * FROM cv_points WHERE source_file_id = ?", (file_id,)
        ).fetchall()
        return [CVPoint.from_sqlite_row(row) for row in rows]

    def update_status(self, point_id: str, status: Status) -> None:
        """Update the status of a CVPoint.

        Args:
            point_id: The UUID of the CVPoint.
            status: The new status value.
        """
        with self._conn:
            self._conn.execute(
                "UPDATE cv_points SET status = ? WHERE id = ?",
                (status.value, point_id),
            )

    def list_by_generation_level(self, level: GenerationLevel) -> List[CVPoint]:
        """Fetch all CVPoints matching the given generation level.

        Args:
            level: Either L1 (raw extraction) or L2 (experience-level refined).

        Returns:
            A list of matching CVPoints.
        """
        rows = self._conn.execute(
            "SELECT * FROM cv_points WHERE generation_level = ?",
            (level.value,),
        ).fetchall()
        return [CVPoint.from_sqlite_row(row) for row in rows]

    def list_approved_with_embeddings(self) -> List[CVPoint]:
        """Fetch all approved CVPoints that have a pre-computed embedding.

        Returns:
            A list of approved CVPoints with non-null embeddings.
        """
        rows = self._conn.execute(
            "SELECT * FROM cv_points WHERE status = ? AND embedding IS NOT NULL",
            (Status.APPROVED.value,),
        ).fetchall()
        return [CVPoint.from_sqlite_row(row) for row in rows]

    def load_approved_embeddings_raw(self) -> List[tuple[str, bytes]]:
        """Fetch (point_id, embedding_blob) pairs for all approved points.

        Returns:
            A list of (point_id, embedding_blob) tuples for approved points
            with non-null embeddings. Used by EmbeddingIndex for fast loading.
        """
        rows = self._conn.execute(
            "SELECT id, embedding FROM cv_points WHERE status = ? AND embedding IS NOT NULL",
            (Status.APPROVED.value,),
        ).fetchall()
        return [(row["id"], row["embedding"]) for row in rows]

    def update_embedding(self, point_id: str, embedding_blob: bytes) -> None:
        """Store a pre-normalized embedding BLOB for a CVPoint.

        Args:
            point_id: The UUID of the CVPoint.
            embedding_blob: The raw float32 bytes of the normalized embedding.
        """
        with self._conn:
            self._conn.execute(
                "UPDATE cv_points SET embedding = ? WHERE id = ?",
                (embedding_blob, point_id),
            )
