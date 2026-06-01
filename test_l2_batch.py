"""Standalone test: run the REAL L2 Batch Editor on L1 draft points.

Prerequisites:
    python test_l1.py   (to populate L1 draft points in the DB)

This script:
1. Fetches L1 draft points for 01_tata-neu
2. Runs the Batch Editor (embed → flag → edit → judge → save)
3. Prints the resulting L2 approved points
"""

import sys

sys.path.insert(0, "src")

from pathlib import Path

from cv_weaver.config import load_settings
from cv_weaver.generator.batch_editor import BatchEditorEngine
from cv_weaver.llm_client.embedder import create_embedder_client
from cv_weaver.llm_client.instructor_wrapper import create_instructor_client
from cv_weaver.models.enums import Status
from cv_weaver.storage.db import get_connection, init_db
from cv_weaver.storage.repository import CVPointRepository

settings = load_settings()
print(f"Generation model: {settings.generation_model}")
print(f"Judge model:      {settings.judge_model}")
print(f"DB path:          {settings.database_path}")
print()

Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
init_db(settings.database_path)
conn = get_connection(settings.database_path)
repo = CVPointRepository(conn)

# Check prerequisites
all_points = repo.list_by_source("01_tata-neu")
if not all_points:
    print("✗ No points found for 01_tata-neu. Run `python test_l1.py` first.")
    conn.close()
    sys.exit(1)

l1_drafts = [p for p in all_points if p.generation_level.value == "l1" and p.classification.status.value == "draft"]
print(f"[SETUP] Found {len(l1_drafts)} L1 draft point(s) for 01_tata-neu")

if not l1_drafts:
    print("✗ No L1 draft points to finalize. They may already be archived or approved.")
    conn.close()
    sys.exit(1)

# Run Batch Editor
llm_client = create_instructor_client(settings)
embedder = create_embedder_client()
engine = BatchEditorEngine(
    llm_client=llm_client,
    embedder=embedder,
    repo=repo,
    settings=settings,
)

print()
print("=" * 60)
print("L2 BATCH EDITOR PIPELINE START")
print("=" * 60)

result = engine.finalize_file("01_tata-neu")

print()
print("=" * 60)
print("L2 BATCH EDITOR PIPELINE COMPLETE")
print("=" * 60)
print(f"File:              {result.file_id}")
print(f"Points in (L1):    {result.points_in}")
print(f"Points out (L2):   {result.points_out}")
print(f"Total LLM latency: {result.total_llm_latency_s:.2f}s")
print()

# Verify DB
l2_approved = [
    p for p in repo.list_by_source("01_tata-neu")
    if p.generation_level.value == "l2" and p.classification.status.value == "approved"
]
print(f"DB: {len(l2_approved)} L2 approved point(s) for 01_tata-neu")
for p in l2_approved:
    parent = p.classification.parent_point_id or "none"
    print(
        f"  [{p.id[:8]}...] parent={parent[:8]}... "
        f"impact={p.scores.impact_score} ats={p.scores.ats_score} "
        f"complete={p.scores.completeness_score}"
    )
    print(f"    {p.rendered_bullet[:75]}...")

# Show archived L1s
archived_l1 = [
    p for p in repo.list_by_source("01_tata-neu")
    if p.generation_level.value == "l1" and p.classification.status.value == "archived"
]
print(f"\nDB: {len(archived_l1)} L1 archived point(s) for 01_tata-neu")

conn.close()
print("\nDone.")
