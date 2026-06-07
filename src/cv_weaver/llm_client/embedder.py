"""Local Ollama embedding client for nomic-embed-text.

INFRASTRUCTURE RULE — TWO ISOLATED CLIENTS:
---------------------------------------------------------------
1. Cloud LLM Client (instructor_wrapper.py):
   - Host: YOUR_CLOUD_OLLAMA_URL (from .env)
   - Usage: text generation, chat, judge calls
   - Never use for embeddings.

2. Local Embedding Client (this file):
   - Host: http://localhost:11434
   - Model: nomic-embed-text
   - Usage: vector embeddings, semantic similarity, RAG
   - Never route to cloud API.

Why local for embeddings?
- nomic-embed-text is a small model (~130MB). Running it locally is free,
  fast, and avoids cloud rate limits.
- Cloud Ollama instances may not host embedding models (confirmed: 401
  on nomic-embed-text for our cloud provider).
- Separation of concerns: text generation latency does not block
  embedding throughput.
"""

import time
from typing import List

import ollama

LOCAL_EMBEDDER_HOST: str = "http://localhost:11434"
LOCAL_EMBEDDER_MODEL: str = "nomic-embed-text"


class EmbedderClient:
    """Local Ollama client for text embeddings.

    Always connects to http://localhost:11434. No auth headers.
    """

    def __init__(self, model: str = LOCAL_EMBEDDER_MODEL):
        self._model = model
        self._client = ollama.Client(
            host=LOCAL_EMBEDDER_HOST,
            timeout=60.0,  # Local inference is fast; 60s is generous
        )

    def embed(self, text: str) -> List[float]:
        """Generate an embedding vector for a single text string."""
        t0 = time.perf_counter()
        print(f"    [EMBED] START {self._model} text={len(text)} chars")

        response = self._client.embed(model=self._model, input=text)
        embedding = response.embeddings[0]

        elapsed = time.perf_counter() - t0
        print(f"    [EMBED] DONE  {self._model} dim={len(embedding)} in {elapsed:.2f}s")
        return embedding

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for multiple texts in one API call."""
        if not texts:
            return []

        t0 = time.perf_counter()
        print(
            f"    [EMBED] START batch {self._model} n={len(texts)} "
            f"total_chars={sum(len(t) for t in texts)}"
        )

        response = self._client.embed(model=self._model, input=texts)
        embeddings = response.embeddings

        elapsed = time.perf_counter() - t0
        print(
            f"    [EMBED] DONE  batch {self._model} n={len(embeddings)} "
            f"dim={len(embeddings[0])} in {elapsed:.2f}s"
        )
        return embeddings


def create_embedder_client() -> EmbedderClient:
    """Factory function for EmbedderClient.

    Returns:
        A configured EmbedderClient pointing at localhost.
    """
    return EmbedderClient()
