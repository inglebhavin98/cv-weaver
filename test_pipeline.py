"""End-to-end pipeline test: Component 1 → Component 2 (L1 + L2) → Component 3.

Orchestrates the full in-scope pipeline with per-stage timing:
1. Setup        — init DB, load settings
2. L1 Generate  — per-story extraction, QnA (auto-skipped), judge, save as draft
3. L2 Batch     — embed, flag, editorial LLM, structural validation, judge, save as approved
4. Verify       — count points by level/status, assert correctness

Run with:
    python test_pipeline.py

Output: per-stage wall time + aggregate summary. Use this data to optimize.
"""

import sys
import time
import builtins
from pathlib import Path

sys.path.insert(0, "src")

# ─── Auto-skip interactive prompts ────────────────────────────────────
# L1 QnA: return "skip" so structural/semantic gaps are accepted as-is
# L2 Approval: detect the approval prompt and return "y" to commit

_original_input = builtins.input

def _smart_input(prompt: str) -> str:
    p = prompt.strip().lower()
    if "approve and commit" in p:
        print(f"[AUTO-APPROVE] {prompt.strip()}")
        return "y"
    print(f"[AUTO-SKIP] {prompt.strip()}")
    return "skip"

builtins.input = _smart_input

# ─── Imports ────────────────────────────────────────────────────────────

from cv_weaver.config import load_settings
from cv_weaver.generator.engine import GeneratorEngine
from cv_weaver.generator.batch_editor import BatchEditorEngine
from cv_weaver.llm_client.embedder import create_embedder_client
from cv_weaver.llm_client.instructor_wrapper import create_instructor_client
from cv_weaver.models.enums import GenerationLevel, Status
from cv_weaver.storage.db import get_connection, init_db
from cv_weaver.storage.repository import CVPointRepository

# ─── Stage Functions ────────────────────────────────────────────────────


def stage_setup() -> dict:
    """Initialize database and settings."""
    t0 = time.perf_counter()
    settings = load_settings()
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_db(db_path)
    conn = get_connection(db_path)
    repo = CVPointRepository(conn)
    elapsed = time.perf_counter() - t0
    print(f"  [SETUP] DB ready at {db_path} in {elapsed:.3f}s")
    return {"settings": settings, "conn": conn, "repo": repo}


def stage_l1_generate(ctx: dict, file_id: str, force: bool = False) -> dict:
    """Run L1 generation on one knowledge base file.

    If force=False and valid L1 drafts already exist, skip re-generation
    to save time when debugging downstream stages.
    """
    settings = ctx["settings"]
    repo = ctx["repo"]

    # Resolve file
    kb = Path(settings.knowledge_base_path)
    candidates = list((kb / "experience").glob(f"{file_id}.md"))
    if not candidates:
        candidates = list((kb / "projects").glob(f"{file_id}.md"))
    if not candidates:
        raise FileNotFoundError(f"No knowledge base file for '{file_id}'")
    file_path = candidates[0]
    source_type = "experience" if "experience" in str(file_path) else "project"

    # Check for existing L1 drafts
    existing = [
        p for p in repo.list_by_source(file_id)
        if p.generation_level == GenerationLevel.L1 and p.classification.status == Status.DRAFT
    ]
    if existing and not force:
        print(f"\n[L1] ──► Reusing {len(existing)} existing L1 draft point(s) (force=False)")
        return {
            "elapsed_s": 0.0,
            "story_count": 0,  # unknown without re-parsing
            "point_count": len(existing),
            "qna_rounds": 0,
            "reused": True,
        }

    # Clear old points for clean run
    repo._conn.execute("DELETE FROM cv_points WHERE source_file_id = ? AND generation_level = 'l1'", (file_id,))
    repo._conn.execute("DELETE FROM cv_points WHERE source_file_id = ? AND generation_level = 'l2'", (file_id,))
    repo._conn.commit()

    client = create_instructor_client(settings)
    engine = GeneratorEngine(client, repo, settings)

    print(f"\n[L1] ──► Generating from {file_path.name} ({source_type})")
    t0 = time.perf_counter()
    result = engine.generate_from_file(file_path, source_type)
    elapsed = time.perf_counter() - t0

    print(f"[L1] ◄── Done in {elapsed:.2f}s")
    print(f"  Stories: {len(result.story_results)}")
    print(f"  Points:  {result.total_points}")
    print(f"  QnA:     {result.total_qna_rounds}")

    return {
        "elapsed_s": elapsed,
        "story_count": len(result.story_results),
        "point_count": result.total_points,
        "qna_rounds": result.total_qna_rounds,
        "reused": False,
    }


def stage_l2_batch(ctx: dict, file_id: str) -> dict:
    """Run L2 Batch Editor on L1 drafts for one file_id.

    Returns dict with timing and result summary.
    """
    settings = ctx["settings"]
    repo = ctx["repo"]

    llm_client = create_instructor_client(settings)
    embedder = create_embedder_client()
    engine = BatchEditorEngine(
        llm_client=llm_client,
        embedder=embedder,
        repo=repo,
        settings=settings,
    )

    print(f"\n[L2] ──► Batch finalization for {file_id}")
    t0 = time.perf_counter()
    result = engine.finalize_file(file_id)
    elapsed = time.perf_counter() - t0

    print(f"[L2] ◄── Done in {elapsed:.2f}s")
    print(f"  Points in:  {result.points_in}")
    print(f"  Points out: {result.points_out}")
    print(f"  LLM time:   {result.total_llm_latency_s:.2f}s")

    return {
        "elapsed_s": elapsed,
        "points_in": result.points_in,
        "points_out": result.points_out,
        "llm_latency_s": result.total_llm_latency_s,
    }


def stage_verify(ctx: dict, file_id: str) -> dict:
    """Verify DB state and assert correctness."""
    repo = ctx["repo"]

    print(f"\n[VERIFY] Checking DB state for {file_id}")
    t0 = time.perf_counter()

    all_points = repo.list_by_source(file_id)

    l1_archived = [
        p for p in all_points
        if p.generation_level == GenerationLevel.L1 and p.classification.status == Status.ARCHIVED
    ]
    l2_approved = [
        p for p in all_points
        if p.generation_level == GenerationLevel.L2 and p.classification.status == Status.APPROVED
    ]
    l1_draft = [
        p for p in all_points
        if p.generation_level == GenerationLevel.L1 and p.classification.status == Status.DRAFT
    ]

    elapsed = time.perf_counter() - t0

    print(f"  L1 archived: {len(l1_archived)}")
    print(f"  L2 approved: {len(l2_approved)}")
    print(f"  L1 draft:    {len(l1_draft)} (should be 0)")

    # Assertions
    assert len(l1_draft) == 0, f"Expected 0 L1 drafts, found {len(l1_draft)}"
    assert len(l2_approved) > 0, f"Expected >0 L2 approved points, found {len(l2_approved)}"

    for p in l2_approved:
        assert p.scores.impact_score >= 0
        assert p.scores.ats_score >= 0
        assert p.scores.completeness_score >= 0
        assert p.classification.parent_point_id is not None

    print(f"  ✓ All assertions passed in {elapsed:.3f}s")

    return {
        "elapsed_s": elapsed,
        "l1_archived": len(l1_archived),
        "l2_approved": len(l2_approved),
    }


# ─── Main Orchestrator ──────────────────────────────────────────────────


def main() -> int:
    """Run the full pipeline with aggregate timing."""
    file_id = "01_tata-neu"
    total_t0 = time.perf_counter()

    print("=" * 60)
    print("CV-WEAVER PIPELINE TEST — Components 1 → 2 → 3")
    print("=" * 60)

    # Stage 1: Setup
    print("\n▶ STAGE 1: Setup")
    ctx = stage_setup()

    # Stage 2: L1 Generation
    print("\n▶ STAGE 2: L1 Generation")
    l1_stats = stage_l1_generate(ctx, file_id)

    # Stage 3: L2 Batch Editor
    print("\n▶ STAGE 3: L2 Batch Editor")
    l2_stats = stage_l2_batch(ctx, file_id)

    # Stage 4: Verification
    print("\n▶ STAGE 4: Verification")
    verify_stats = stage_verify(ctx, file_id)

    # Cleanup
    ctx["conn"].close()

    # ── Aggregate Summary ───────────────────────────────────────────────
    total_elapsed = time.perf_counter() - total_t0

    print()
    print("=" * 60)
    print("PIPELINE SUMMARY")
    print("=" * 60)
    print(f"{'Stage':<20} {'Wall Time (s)':>15} {'Details'}")
    print("-" * 60)
    print(f"{'Setup':<20} {0.0:>15.3f} {'DB init'}")
    l1_detail = f"{l1_stats['point_count']} points, {l1_stats['qna_rounds']} QnA rounds"
    if l1_stats.get("reused"):
        l1_detail = f"{l1_stats['point_count']} points (reused from DB)"
    print(f"{'L1 Generation':<20} {l1_stats['elapsed_s']:>15.2f} {l1_detail}")
    print(f"{'L2 Batch Editor':<20} {l2_stats['elapsed_s']:>15.2f} {l2_stats['points_in']}→{l2_stats['points_out']} points")
    print(f"{'Verification':<20} {verify_stats['elapsed_s']:>15.3f} {verify_stats['l2_approved']} L2 approved")
    print("-" * 60)
    print(f"{'TOTAL':<20} {total_elapsed:>15.2f}")
    print("=" * 60)
    print("\n✓ Pipeline complete. All in-scope components verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
