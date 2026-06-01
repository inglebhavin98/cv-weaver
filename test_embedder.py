"""Standalone test: verify EmbedderClient connects and generates embeddings."""

import sys
sys.path.insert(0, "src")

from cv_weaver.config import load_settings
from cv_weaver.llm_client.embedder import create_embedder_client

settings = load_settings()
print(f"Embedding model: {settings.embedding_model}")
print(f"Ollama URL:      {settings.ollama_base_url}")
print()

client = create_embedder_client()

# ─── Single embedding ──────────────────────────────────────────────────
text = "Led a team of 5 engineers to redesign the payments API, reducing P95 latency from 800ms to 120ms."
print(f"[SINGLE] Embedding text: {text[:60]}...")
vector = client.embed(text)
print(f"[SINGLE] Result: dim={len(vector)} | first_5={vector[:5]}")
print()

# ─── Batch embedding ───────────────────────────────────────────────────
texts = [
    "Architected a real-time event streaming platform using Kafka and Redis.",
    "Optimized CI/CD pipeline, cutting build times by 40% across 12 microservices.",
    "Built a React dashboard used by 200+ internal stakeholders daily.",
]
print(f"[BATCH] Embedding {len(texts)} texts...")
vectors = client.embed_batch(texts)
for i, v in enumerate(vectors):
    print(f"  [{i}] dim={len(v)} | first_5={v[:5]}")
print()

# ─── Sanity checks ─────────────────────────────────────────────────────
assert len(vector) > 0, "Single embedding returned empty vector"
assert len(vectors) == len(texts), "Batch count mismatch"
for v in vectors:
    assert len(v) == len(vector), f"Dimension mismatch: {len(v)} vs {len(vector)}"

print("✓ All sanity checks passed.")
print("Done.")
