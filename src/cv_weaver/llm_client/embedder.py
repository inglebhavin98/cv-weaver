"""Lightweight embedding client for Ollama Cloud.

Wraps ollama.embed() to generate vector embeddings for text.
Used by the RAG system to compare CV points against job descriptions.

Why not use a separate embedding library?
- Ollama Cloud provides embedding models (nomic-embed-text) via the same API.
- Consistency: same auth, host, timeout handling as the LLM client.
- The ollama library handles batching and normalization.

Learnings from kimi-k2.6 integration apply here too:
- stream is not relevant for embeddings (single-shot API).
- timeout should still be generous (90–150s) for large batches.
"""

import time
from typing import List

import ollama

from cv_weaver.config import Settings


class EmbedderClient:
    """Native Ollama client for text embeddings.

    Generates dense vector representations of text for similarity search.
    Uses the model configured in settings.embedding_model (default: nomic-embed-text).
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._model = settings.embedding_model

        headers: dict[str, str] = {}
        if settings.ollama_api_key and settings.ollama_api_key != "ollama":
            headers["Authorization"] = f"Bearer {settings.ollama_api_key}"

        host = str(settings.ollama_base_url).rstrip("/")
        if host.endswith("/v1"):
            host = host[:-3]

        self._client = ollama.Client(host=host, headers=headers, timeout=90.0)

    def embed(self, text: str) -> List[float]:
        """Generate an embedding vector for a single text string.

        Args:
            text: The text to embed. Typically a rendered_bullet or JD text.

        Returns:
            A list of float values representing the embedding vector.

        Raises:
            Exception: If the Ollama API returns an error.
        """
        t0 = time.perf_counter()
        print(f"    [EMBED] START {self._model} text={len(text)} chars")

        response = self._client.embed(model=self._model, input=text)
        embedding = response.embeddings[0]

        elapsed = time.perf_counter() - t0
        print(f"    [EMBED] DONE  {self._model} dim={len(embedding)} in {elapsed:.2f}s")
        return embedding

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for multiple texts in one API call.

        Args:
            texts: List of text strings to embed.

        Returns:
            A list of embedding vectors, one per input text.
        """
        if not texts:
            return []

        t0 = time.perf_counter()
        print(f"    [EMBED] START batch {self._model} n={len(texts)} total_chars={sum(len(t) for t in texts)}")

        response = self._client.embed(model=self._model, input=texts)
        embeddings = response.embeddings

        elapsed = time.perf_counter() - t0
        print(f"    [EMBED] DONE  batch {self._model} n={len(embeddings)} dim={len(embeddings[0])} in {elapsed:.2f}s")
        return embeddings


def create_embedder_client(settings: Settings | None = None) -> EmbedderClient:
    """Factory function for EmbedderClient.

    Args:
        settings: Optional Settings. If None, loads from `.env`.

    Returns:
        A configured EmbedderClient ready for embed() calls.
    """
    if settings is None:
        from cv_weaver.config import load_settings

        settings = load_settings()
    return EmbedderClient(settings)
