"""Embedding index for RAG-based CV point retrieval.

Provides cosine-similarity search over CV point embeddings.
Embeddings are cached in-memory for fast repeated queries,
with lazy loading from SQLite and write-through persistence.

Why in-memory cache?
- For a CLI tool, the user runs multiple queries per session.
- Re-loading 3MB of float32 BLOBs from SQLite every time is wasteful.
- A module-level singleton is acceptable since this is not a web server.
"""

import math
import struct
from typing import Dict, List, Optional, Tuple

from cv_weaver.models.schemas import CVPoint
from cv_weaver.storage.repository import CVPointRepository


def _blob_to_vector(blob: bytes) -> List[float]:
    """Unpack a BLOB of float32 bytes into a Python list of floats."""
    # Each float is 4 bytes (float32)
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


def _vector_to_blob(vector: List[float]) -> bytes:
    """Pack a Python list of floats into float32 bytes."""
    return struct.pack(f"{len(vector)}f", *vector)


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors.

    Returns a value in [-1, 1]. For normalized embeddings (unit vectors),
    this is equivalent to the dot product and ranges [0, 1].
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingIndex:
    """In-memory index of CV point embeddings with similarity search.

    Usage:
        index = EmbeddingIndex(repo)
        index.load_approved()          # load all approved points with embeddings
        results = index.search(jd_vector, top_k=5)
    """

    def __init__(self, repo: CVPointRepository):
        self._repo = repo
        # Map: point_id -> embedding vector
        self._vectors: Dict[str, List[float]] = {}
        # Map: point_id -> CVPoint (for returning full objects)
        self._points: Dict[str, CVPoint] = {}
        self._dirty: set[str] = set()

    def load_approved(self) -> None:
        """Load all approved points that have pre-computed embeddings."""
        raw_pairs = self._repo.load_approved_embeddings_raw()
        for point_id, blob in raw_pairs:
            vector = _blob_to_vector(blob)
            point = self._repo.get_by_id(point_id)
            if point is None:
                continue  # Shouldn't happen, but be defensive
            self._vectors[point_id] = vector
            self._points[point_id] = point

    def add(self, point_id: str, vector: List[float], point: CVPoint) -> None:
        """Add or update an embedding in the index."""
        self._vectors[point_id] = vector
        self._points[point_id] = point
        self._dirty.add(point_id)

    def search(self, query_vector: List[float], top_k: int = 5) -> List[Tuple[CVPoint, float]]:
        """Find the top-k most similar points to the query vector.

        Returns:
            A list of (CVPoint, similarity_score) tuples, sorted descending by score.
        """
        if not self._vectors:
            return []

        scored = []
        for point_id, vector in self._vectors.items():
            sim = _cosine_similarity(query_vector, vector)
            scored.append((point_id, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:top_k]

        results = []
        for point_id, sim in top:
            point = self._points.get(point_id)
            if point:
                results.append((point, sim))
        return results

    def persist(self) -> None:
        """Write dirty embeddings back to SQLite via the repository."""
        for point_id in self._dirty:
            vector = self._vectors[point_id]
            blob = _vector_to_blob(vector)
            self._repo.update_embedding(point_id, blob)
        self._dirty.clear()
