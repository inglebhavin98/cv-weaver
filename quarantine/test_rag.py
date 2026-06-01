"""Standalone test: verify RAG retrieval over approved L1 points with embeddings.

If no approved points exist, this script auto-approves existing L1 points and
computes their embeddings so the test is self-contained.
"""

import sys
sys.path.insert(0, "src")

from pathlib import Path

from cv_weaver.config import load_settings
from cv_weaver.llm_client.embedder import create_embedder_client
from cv_weaver.llm_client.instructor_wrapper import create_instructor_client
from cv_weaver.models.enums import Status
from cv_weaver.storage.db import get_connection, init_db
from cv_weaver.storage.embeddings import EmbeddingIndex
from cv_weaver.storage.repository import CVPointRepository

settings = load_settings()
print(f"DB path:    {settings.database_path}")
print(f"Embed model: {settings.embedding_model}")
print()

Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
init_db(settings.database_path)
conn = get_connection(settings.database_path)
repo = CVPointRepository(conn)

# ─── Bootstrap: ensure approved points with embeddings exist ─────────
approved = repo.list_by_status(Status.APPROVED)
print(f"[BOOTSTRAP] Approved points in DB: {len(approved)}")

embedder = create_embedder_client(settings)

if not approved:
    draft_points = repo.list_by_status(Status.DRAFT)
    l1_drafts = [p for p in draft_points if p.generation_level.value == "l1"]
    print(f"[BOOTSTRAP] Found {len(l1_drafts)} L1 draft point(s). Auto-approving + embedding...")

    for p in l1_drafts:
        repo.update_status(p.id, Status.APPROVED)
        blob = embedder.embed(p.rendered_bullet)
        from cv_weaver.storage.embeddings import _vector_to_blob
        repo.update_embedding(p.id, _vector_to_blob(blob))
        print(f"  [BOOTSTRAP] approved + embedded {p.id[:8]}...")

    approved = repo.list_by_status(Status.APPROVED)
    print(f"[BOOTSTRAP] Now have {len(approved)} approved point(s).")

if not approved:
    print("\n✗ No points in DB. Run `python test_l1.py` first to populate L1 points.")
    conn.close()
    sys.exit(1)

# ─── Load embedding index ──────────────────────────────────────────────
print(f"\n[INDEX] Loading EmbeddingIndex...")
index = EmbeddingIndex(repo)
index.load_approved()
print(f"[INDEX] Loaded {len(index._vectors)} vector(s).")

if not index._vectors:
    print("\n✗ Index is empty even though approved points exist. Check embedding BLOBs.")
    conn.close()
    sys.exit(1)

# ─── Search with a sample JD ───────────────────────────────────────────
sample_jd = """
Senior Backend Engineer
We are looking for an experienced backend engineer to lead our payments team.
Required: Python, Redis, Kafka, microservices architecture.
Nice to have: experience with high-throughput systems and latency optimization.
Responsibilities: redesign core APIs, mentor junior engineers, reduce latency.
"""

print(f"\n[SEARCH] Embedding JD and searching (top_k=5)...")
jd_vector = embedder.embed(sample_jd)
results = index.search(jd_vector, top_k=5)

print(f"[SEARCH] Results: {len(results)}")
for i, (point, sim) in enumerate(results, start=1):
    print(f"  [{i}] sim={sim:.4f} | {point.rendered_bullet[:70]}...")
    print(f"       skills={point.metadata.skills_utilized} metrics={point.metadata.impact_metrics}")

conn.close()
print("\nDone.")
