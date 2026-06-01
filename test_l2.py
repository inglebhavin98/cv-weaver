"""Standalone test: run full L2 pipeline (JD analysis → RAG → rewrite → selection → save).

Bootstraps approved + embedded L1 points if needed, then runs CustomizerEngine.
Auto-skips any user input prompts by returning 'skip'.
"""

import sys
sys.path.insert(0, "src")

import builtins
from pathlib import Path

# Auto-skip any QnA that might leak through
builtins.input = lambda p: (print(f"[AUTO-SKIP] {p.strip()}"), "skip")[1]

from cv_weaver.config import load_settings
from cv_weaver.customizer.engine import CustomizerEngine
from cv_weaver.llm_client.embedder import create_embedder_client
from cv_weaver.llm_client.instructor_wrapper import create_instructor_client
from cv_weaver.models.enums import Status
from cv_weaver.storage.db import get_connection, init_db
from cv_weaver.storage.embeddings import EmbeddingIndex, _vector_to_blob
from cv_weaver.storage.repository import CVPointRepository

settings = load_settings()
print(f"Generation model: {settings.generation_model}")
print(f"Embedding model:  {settings.embedding_model}")
print(f"DB path:          {settings.database_path}")
print()

Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
init_db(settings.database_path)
conn = get_connection(settings.database_path)
repo = CVPointRepository(conn)

# ─── Bootstrap: ensure approved L1 points with embeddings exist ──────
approved = repo.list_by_status(Status.APPROVED)
print(f"[BOOTSTRAP] Approved points: {len(approved)}")

embedder = create_embedder_client(settings)

if not approved:
    draft_points = repo.list_by_status(Status.DRAFT)
    l1_drafts = [p for p in draft_points if p.generation_level.value == "l1"]
    print(f"[BOOTSTRAP] Found {len(l1_drafts)} L1 draft point(s). Auto-approving + embedding...")
    for p in l1_drafts:
        repo.update_status(p.id, Status.APPROVED)
        vec = embedder.embed(p.rendered_bullet)
        repo.update_embedding(p.id, _vector_to_blob(vec))
        print(f"  [BOOTSTRAP] {p.id[:8]}... approved + embedded")
    approved = repo.list_by_status(Status.APPROVED)
    print(f"[BOOTSTRAP] Now have {len(approved)} approved point(s).")

if not approved:
    print("\n✗ No points in DB. Run `python test_l1.py` first.")
    conn.close()
    sys.exit(1)

# ─── Build embedding index ─────────────────────────────────────────────
print(f"\n[INDEX] Loading EmbeddingIndex...")
index = EmbeddingIndex(repo)
index.load_approved()
print(f"[INDEX] Loaded {len(index._vectors)} vector(s).")

if not index._vectors:
    print("\n✗ Index empty. Check that approved points have embeddings.")
    conn.close()
    sys.exit(1)

# ─── Run L2 Customizer ─────────────────────────────────────────────────
llm_client = create_instructor_client(settings)
engine = CustomizerEngine(
    llm_client=llm_client,
    embedder=embedder,
    repo=repo,
    index=index,
    settings=settings,
)

sample_jd = """
Senior Backend Engineer — Fintech Payments

About the role:
We are seeking a senior backend engineer to own our core payments platform.
You will lead architectural decisions, mentor junior engineers, and drive
latency and reliability improvements across high-throughput systems.

Requirements:
- 5+ years building production backend systems in Python or Go
- Deep experience with distributed systems: Kafka, Redis, PostgreSQL
- Track record of reducing latency and improving system reliability
- Experience with microservices and event-driven architecture
- Strong communication skills and ability to mentor

Nice to have:
- Experience in fintech or regulated environments
- Knowledge of PCI-DSS or security best practices
- Prior work with payment gateways or ledgers
"""

print("\n" + "=" * 60)
print("L2 CUSTOMIZER PIPELINE START")
print("=" * 60)

result = engine.customize_for_jd(sample_jd, top_k=10)

print()
print("=" * 60)
print("L2 CUSTOMIZER PIPELINE COMPLETE")
print("=" * 60)
print(f"JD role title:       {result.jd_analysis.role_title}")
print(f"L1 points searched:    {result.total_l1_points_searched}")
print(f"Points rewritten:      {result.points_rewritten}")
print(f"Points selected:       {result.points_selected}")
print(f"Coverage score:        {result.coverage_score}")
print(f"Total LLM latency:     {result.total_llm_latency_s:.2f}s")
print()

print("─" * 60)
print("SELECTED L2 POINTS")
print("─" * 60)
for p in result.selected_points:
    parent = p.classification.parent_point_id or "none"
    print(f"  [{p.id[:8]}...] parent={parent[:8]}... | {p.rendered_bullet[:70]}...")
    print(f"    skills={p.metadata.skills_utilized} metrics={p.metadata.impact_metrics}")

conn.close()
print("\nDone.")
