"""Quick end-to-end test: run L1 pipeline on sample file."""

import sys
sys.path.insert(0, "src")

import builtins
import time

# Auto-skip QnA
builtins.input = lambda p: (print(f"[AUTO-SKIP] {p.strip()}"), "skip")[1]

from pathlib import Path
from cv_weaver.config import load_settings
from cv_weaver.llm_client.instructor_wrapper import create_instructor_client
from cv_weaver.generator.engine import GeneratorEngine
from cv_weaver.storage.db import init_db, get_connection
from cv_weaver.storage.repository import CVPointRepository

settings = load_settings()
print(f"Model: {settings.generation_model}")
print(f"DB: {settings.database_path}")
print(f"Ollama URL: {settings.ollama_base_url}")
print()

# Init DB
Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
init_db(settings.database_path)
conn = get_connection(settings.database_path)
repo = CVPointRepository(conn)

# Clear old data for clean test
repo._conn.execute("DELETE FROM cv_points WHERE source_file_id = '01_tata-neu'")
repo._conn.commit()
print("Old data cleared.")

client = create_instructor_client(settings)
engine = GeneratorEngine(client, repo, settings)

f = Path("data/knowledge_base/experience/01_tata-neu.md")
print(f"Processing: {f}")
print("Running L1 pipeline (drafter + QnA + judge + DB save)...")
print("=" * 60)
print()

total_t0 = time.perf_counter()
result = engine.generate_from_file(f, "experience")
total_elapsed = time.perf_counter() - total_t0

print()
print("=" * 60)
print("L1 PIPELINE COMPLETE")
print("=" * 60)
print(f"File: {result.file_id}")
print(f"Stories: {len(result.story_results)}")
print(f"Total points: {result.total_points}")
print(f"Total QnA rounds: {result.total_qna_rounds}")
print(f"TOTAL WALL TIME: {total_elapsed:.2f}s")
print()

# --- Timing breakdown per story / candidate ---
print("─" * 60)
print("BREAKDOWN")
print("─" * 60)

llm_calls = {"drafter": 0, "refiner": 0, "judge": 0, "total": 0}
llm_time = {"drafter": 0.0, "refiner": 0.0, "judge": 0.0, "total": 0.0}

for sr in result.story_results:
    print(f"Story: {sr.story_title}")
    for cr in sr.candidates:
        bullet = cr.point.rendered_bullet[:70]
        conv = "✓" if cr.converged else "✗"
        print(
            f"  [{conv}] {bullet}...  "
            f"impact={cr.evaluation.impact_score} "
            f"ats={cr.evaluation.ats_score} "
            f"complete={cr.evaluation.completeness_score} "
            f"qna={cr.qna_rounds}"
        )
    print()

# Verify DB
pts = repo.list_by_source("01_tata-neu")
print(f"DB: {len(pts)} point(s) saved for 01_tata-neu")
for p in pts:
    print(f"  [{p.id[:8]}] {p.generation_level.value} {p.classification.status.value}: {p.rendered_bullet[:55]}...")

conn.close()
print()
print("=" * 60)
print("BENCHMARK SUMMARY")
print("=" * 60)
print(f"Total wall time:       {total_elapsed:.2f}s")
print(f"Stories processed:     {len(result.story_results)}")
print(f"Candidates generated:  {result.total_points}")
print(f"QnA rounds total:      {result.total_qna_rounds}")
print(f"Avg per story:         {total_elapsed / max(len(result.story_results), 1):.2f}s")
print(f"Avg per candidate:     {total_elapsed / max(result.total_points, 1):.2f}s")
print("\nDone.")
