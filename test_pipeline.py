"""End-to-end pipeline test: Component 1 → Component 2 (L1 + L2) → Component 3.

Orchestrates the full in-scope pipeline with per-stage timing:
1. Setup        — init DB, load settings
2. L1 Generate  — per-story extraction, QnA (auto-skipped), judge, save as draft
3. L2 Batch     — embed, flag, editorial LLM, structural validation, judge, save as approved
4. Verify       — count points by level/status, assert correctness

Run with:
    python test_pipeline.py                    # process all knowledge base files
    python test_pipeline.py --fresh            # wipe DB and reprocess everything
    python test_pipeline.py --file 01_tata-neu # process one file only

Output: per-stage wall time + aggregate summary. Use this data to optimize.
"""

import argparse
import builtins
import sys
import time
from pathlib import Path
from typing import List, Tuple

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


# ─── Imports ────────────────────────────────────────────────────────────

from cv_weaver.config import load_settings
from cv_weaver.generator.engine import GeneratorEngine
from cv_weaver.generator.batch_editor import BatchEditorEngine
from cv_weaver.llm_client.embedder import create_embedder_client
from cv_weaver.llm_client.instructor_wrapper import create_instructor_client
from cv_weaver.models.enums import GenerationLevel, Status
from cv_weaver.storage.db import get_connection, init_db
from cv_weaver.storage.repository import CVPointRepository

# ─── File Discovery ─────────────────────────────────────────────────────


def discover_files(kb_path: Path) -> List[Tuple[Path, str]]:
    """Find all knowledge base markdown files.

    Returns list of (file_path, source_type) where source_type is
    'experience' or 'project'.
    """
    files: List[Tuple[Path, str]] = []
    for p in sorted((kb_path / "experience").glob("*.md")):
        files.append((p, "experience"))
    for p in sorted((kb_path / "projects").glob("*.md")):
        files.append((p, "project"))
    return files


def resolve_file(kb_path: Path, file_id: str) -> Tuple[Path, str]:
    """Resolve a specific file_id to (path, source_type)."""
    candidates = list((kb_path / "experience").glob(f"{file_id}.md"))
    source_type = "experience"
    if not candidates:
        candidates = list((kb_path / "projects").glob(f"{file_id}.md"))
        source_type = "project"
    if not candidates:
        raise FileNotFoundError(f"No knowledge base file for '{file_id}'")
    return candidates[0], source_type


# ─── Stage Functions ────────────────────────────────────────────────────


def stage_setup(fresh: bool = False) -> dict:
    """Initialize database and settings."""
    t0 = time.perf_counter()
    settings = load_settings()
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if fresh and db_path.exists():
        db_path.unlink()
        print(f"  [SETUP] Wiped existing DB at {db_path}")

    init_db(db_path)
    conn = get_connection(db_path)
    repo = CVPointRepository(conn)
    elapsed = time.perf_counter() - t0
    print(f"  [SETUP] DB ready at {db_path} in {elapsed:.3f}s")
    return {"settings": settings, "conn": conn, "repo": repo}


def stage_l1_generate(
    ctx: dict,
    file_path: Path,
    source_type: str,
    force: bool = False,
) -> dict:
    """Run L1 generation on one knowledge base file.

    Checkpoint logic:
    - If L2 approved points already exist and force=False → skip entirely.
    - If L1 drafts already exist and force=False → skip L1, return reused.
    - Otherwise → clear old points and regenerate.
    """
    settings = ctx["settings"]
    repo = ctx["repo"]
    file_id = file_path.stem

    # CHECKPOINT 1: Already fully processed (L2 approved exists)
    l2_approved_count = repo.count_by_source_and_level_status(
        file_id, GenerationLevel.L2, Status.APPROVED
    )
    if l2_approved_count > 0 and not force:
        print(f"\n[CHECKPOINT] {file_id}: already has {l2_approved_count} L2 approved point(s). Skipping L1+L2.")
        return {
            "elapsed_s": 0.0,
            "story_count": 0,
            "point_count": l2_approved_count,
            "qna_rounds": 0,
            "semantic_rounds": 0,
            "skipped": True,
        }

    # CHECKPOINT 2: L1 drafts already exist → reuse for L2
    existing = [
        p for p in repo.list_by_source(file_id)
        if p.generation_level == GenerationLevel.L1 and p.classification.status == Status.DRAFT
    ]
    if existing and not force:
        print(f"\n[CHECKPOINT] {file_id}: reusing {len(existing)} existing L1 draft(s). Skipping L1 generation.")
        return {
            "elapsed_s": 0.0,
            "story_count": 0,
            "point_count": len(existing),
            "qna_rounds": 0,
            "semantic_rounds": 0,
            "reused": True,
        }

    # Clear old points for clean run on this file
    repo._conn.execute(
        "DELETE FROM cv_points WHERE source_file_id = ? AND generation_level = 'l1'",
        (file_id,),
    )
    repo._conn.execute(
        "DELETE FROM cv_points WHERE source_file_id = ? AND generation_level = 'l2'",
        (file_id,),
    )
    repo._conn.commit()

    client = create_instructor_client(settings)
    engine = GeneratorEngine(client, repo, settings)

    print(f"\n[L1] ──► {file_path.name} ({source_type})")
    t0 = time.perf_counter()
    result = engine.generate_from_file(file_path, source_type)
    elapsed = time.perf_counter() - t0

    print(f"[L1] ◄── {elapsed:.2f}s | {len(result.story_results)} stories → {result.total_points} points | QnA: {result.total_qna_rounds} (semantic: {result.total_semantic_rounds})")

    return {
        "elapsed_s": elapsed,
        "story_count": len(result.story_results),
        "point_count": result.total_points,
        "qna_rounds": result.total_qna_rounds,
        "semantic_rounds": result.total_semantic_rounds,
        "reused": False,
    }


def stage_l2_batch(ctx: dict, file_id: str) -> dict:
    """Run L2 Batch Editor on L1 drafts for one file_id."""
    settings = ctx["settings"]
    repo = ctx["repo"]

    # CHECKPOINT: Already has L2 approved points → skip
    l2_approved_count = repo.count_by_source_and_level_status(
        file_id, GenerationLevel.L2, Status.APPROVED
    )
    if l2_approved_count > 0:
        print(f"\n[CHECKPOINT] {file_id}: already has {l2_approved_count} L2 approved point(s). Skipping L2.")
        return {"elapsed_s": 0.0, "points_in": 0, "points_out": l2_approved_count, "llm_latency_s": 0.0, "skipped": True}

    # Check if there are any L1 drafts to process
    drafts = [
        p for p in repo.list_by_source(file_id)
        if p.generation_level == GenerationLevel.L1 and p.classification.status == Status.DRAFT
    ]
    if not drafts:
        print(f"\n[L2] ──► {file_id}: no L1 drafts to process")
        return {"elapsed_s": 0.0, "points_in": 0, "points_out": 0, "llm_latency_s": 0.0}

    llm_client = create_instructor_client(settings)
    embedder = create_embedder_client()
    engine = BatchEditorEngine(
        llm_client=llm_client,
        embedder=embedder,
        repo=repo,
        settings=settings,
    )

    print(f"\n[L2] ──► {file_id}")
    t0 = time.perf_counter()
    result = engine.finalize_file(file_id)
    elapsed = time.perf_counter() - t0

    print(f"[L2] ◄── {elapsed:.2f}s | {result.points_in}→{result.points_out} points | LLM: {result.total_llm_latency_s:.2f}s")

    return {
        "elapsed_s": elapsed,
        "points_in": result.points_in,
        "points_out": result.points_out,
        "llm_latency_s": result.total_llm_latency_s,
    }


def stage_verify_all(ctx: dict, file_ids: List[str]) -> dict:
    """Verify DB state across all processed files."""
    repo = ctx["repo"]

    print(f"\n[VERIFY] Checking DB state for {len(file_ids)} file(s)")
    t0 = time.perf_counter()

    all_points: list = []
    for fid in file_ids:
        all_points.extend(repo.list_by_source(fid))

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


def stage_print_bullets(ctx: dict, file_ids: List[str]) -> None:
    """Query the DB and print all L2 approved bullets in a clean, copy-pasteable format."""
    repo = ctx["repo"]
    print("\n" + "=" * 70)
    print("APPROVED CV BULLETS")
    print("=" * 70)

    for fid in file_ids:
        points = [
            p for p in repo.list_by_source(fid)
            if p.generation_level == GenerationLevel.L2 and p.classification.status == Status.APPROVED
        ]
        if not points:
            continue

        # Sort by impact score descending
        points.sort(key=lambda p: p.scores.impact_score, reverse=True)

        # Extract company from file_id or point source
        company = fid.replace("-", " ").title()

        print(f"\n📄 {fid}  ({len(points)} point(s))")
        print("-" * 70)
        for i, p in enumerate(points, start=1):
            scores = f"impact={p.scores.impact_score} ats={p.scores.ats_score} complete={p.scores.completeness_score}"
            print(f"  {i}. [{scores}] {p.rendered_bullet}")

    print("\n" + "=" * 70)
    print("Tip: Run with --no-auto-skip to answer QnA questions interactively")
    print("     and improve low-score bullets (e.g., 5/5/5 → 9/9/9).")
    print("=" * 70)


def main() -> int:
    parser = argparse.ArgumentParser(description="CV-Weaver end-to-end pipeline")
    parser.add_argument("--fresh", action="store_true", help="Wipe DB and reprocess everything")
    parser.add_argument("--file", type=str, help="Process one specific file_id only")
    parser.add_argument("--force", action="store_true", help="Force re-generation even if drafts exist")
    parser.add_argument("--no-auto-skip", action="store_true", help="Answer QnA questions interactively instead of auto-skipping")
    args = parser.parse_args()

    # Toggle auto-skip based on CLI flag
    if not args.no_auto_skip:
        builtins.input = _smart_input
    else:
        print("\n⚡ INTERACTIVE MODE: You will be asked QnA questions. Type 'skip' to accept as-is.")

    total_t0 = time.perf_counter()

    print("=" * 60)
    print("CV-WEAVER PIPELINE — Components 1 → 2 → 3")
    print("=" * 60)

    # Stage 1: Setup
    print("\n▶ STAGE 1: Setup")
    ctx = stage_setup(fresh=args.fresh)
    settings = ctx["settings"]

    # Resolve files to process
    kb = Path(settings.knowledge_base_path)
    if args.file:
        files_to_process = [resolve_file(kb, args.file)]
    else:
        files_to_process = discover_files(kb)

    if not files_to_process:
        print("\n⚠ No knowledge base files found.")
        print(f"   Add .md files to {kb / 'experience'} or {kb / 'projects'}")
        return 1

    print(f"\n  Files to process: {len(files_to_process)}")
    for fp, st in files_to_process:
        print(f"    • {fp.name} ({st})")

    # Stage 2: L1 Generation (per file)
    print("\n▶ STAGE 2: L1 Generation")
    l1_results: List[dict] = []
    for file_path, source_type in files_to_process:
        stats = stage_l1_generate(ctx, file_path, source_type, force=args.force)
        l1_results.append(stats)

    # Stage 3: L2 Batch Editor (per file)
    print("\n▶ STAGE 3: L2 Batch Editor")
    l2_results: List[dict] = []
    for file_path, _ in files_to_process:
        stats = stage_l2_batch(ctx, file_path.stem)
        l2_results.append(stats)

    # Stage 4: Verification (global)
    file_ids = [fp.stem for fp, _ in files_to_process]
    print("\n▶ STAGE 4: Verification")
    verify_stats = stage_verify_all(ctx, file_ids)

    # Stage 5: Print approved bullets
    print("\n▶ STAGE 5: Print Approved Bullets")
    stage_print_bullets(ctx, file_ids)

    # Cleanup
    ctx["conn"].close()

    # ── Aggregate Summary ───────────────────────────────────────────────
    total_elapsed = time.perf_counter() - total_t0
    total_l1_time = sum(r["elapsed_s"] for r in l1_results)
    total_l2_time = sum(r["elapsed_s"] for r in l2_results)
    total_points_l1 = sum(r["point_count"] for r in l1_results)
    total_points_l2 = sum(r["points_out"] for r in l2_results)
    total_qna = sum(r["qna_rounds"] for r in l1_results)
    total_semantic = sum(r["semantic_rounds"] for r in l1_results)
    total_llm_l2 = sum(r["llm_latency_s"] for r in l2_results)

    # Count skipped/reused files for visibility
    skipped_l1 = sum(1 for r in l1_results if r.get("skipped"))
    reused_l1 = sum(1 for r in l1_results if r.get("reused"))
    skipped_l2 = sum(1 for r in l2_results if r.get("skipped"))

    print()
    print("=" * 60)
    print("PIPELINE SUMMARY")
    print("=" * 60)
    print(f"{'Stage':<22} {'Wall Time (s)':>12} {'Details'}")
    print("-" * 60)
    print(f"{'Setup':<22} {0.0:>12.3f} {'DB init'}")
    l1_detail = f"{total_points_l1} points, {total_qna} QnA rounds ({total_semantic} semantic)"
    if skipped_l1:
        l1_detail += f", {skipped_l1} skipped"
    if reused_l1:
        l1_detail += f", {reused_l1} reused"
    print(f"{'L1 Generation':<22} {total_l1_time:>12.2f} {l1_detail}")
    l2_detail = f"{verify_stats['l1_archived']}→{verify_stats['l2_approved']} points"
    if skipped_l2:
        l2_detail += f", {skipped_l2} skipped"
    print(f"{'L2 Batch Editor':<22} {total_l2_time:>12.2f} {l2_detail}")
    print(f"{'  └─ L2 LLM time':<22} {total_llm_l2:>12.2f} {'editorial + judge'}")
    print(f"{'Verification':<22} {verify_stats['elapsed_s']:>12.3f} {'assertions'}")
    print("-" * 60)
    print(f"{'TOTAL':<22} {total_elapsed:>12.2f}")
    print("=" * 60)
    print(f"\n✓ Pipeline complete. {verify_stats['l2_approved']} approved points across {len(file_ids)} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
