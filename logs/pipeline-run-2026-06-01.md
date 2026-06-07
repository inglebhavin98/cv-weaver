# Pipeline Run Log — 2026-06-01
## Branch: feat/l1-pipeline
## Scope: Components 1-3 (L1 Generator → L2 Batch Editor → Storage)

---

### Aggregate Timing

| Stage | Wall Time (s) | Details |
|-------|--------------|---------|
| Setup | 0.00 | DB init |
| L1 Generation | 1,488.85 | 6 points, 6 QnA rounds |
| L2 Batch Editor | 358.98 | 6→6 points |
| Verification | 0.00 | 6 L2 approved, 6 L1 archived |
| **TOTAL** | **1,847.90** | ~30m 48s |

---

### L1 Breakdown (per story)

- **Story 1 (Payment Orchestration Overhaul):** 2 candidates in 543.64s
- **Story 2 (Cache Layer Redesign):** 2 candidates in ~430s (prober retry on attempt 1 due to fractional confidence, succeeded on attempt 2)
- **Story 3 (Team Onboarding):** 2 candidates in ~515s

### L2 Breakdown

- **FETCH:** 6 L1 draft points fetched
- **EMBED:** 6 points embedded via nomic-embed-text (dim=768) in 0.90s
- **MATH FLAGGER:** 0 merge candidate pairs flagged (no duplicates detected)
- **EDITORIAL LLM:** BatchEditorOutput in 271.62s (1 retry due to `target_l1_ids` schema mismatch, succeeded on attempt 2)
- **JUDGE (×6):** glm-5.1:cloud evaluations, total ~86.4s
  - Impact scores: 10, 10, 10, 9, 10, 8
  - ATS scores: 9, 9, 10, 9, 8, 8
  - Completeness scores: 10, 10, 10, 9, 10, 8
- **SAVE:** 6 points saved as `approved`, 6 L1 drafts archived

---

### Key Observations

1. **No deduplication triggered:** All 6 points were unique enough that cosine similarity < 0.85. This is expected for 3 distinct stories with different focus areas.
2. **LLM retry occurred:** BatchEditorOutput needed 1 retry (279s total → 271.62s successful). Schema mismatch on `target_l1_ids` — fixed by retry loop.
3. **Prober retry occurred:** Story 2 candidate 2 had a fractional confidence value on attempt 1, succeeded on attempt 2.
4. **QnA auto-skipped:** All 6 QnA rounds were automatically skipped (deterministic rules passed first try).
5. **All 6 points kept:** Editorial LLM decided all 6 points were distinct and worth keeping. No merges or splits needed.

---

### Bottleneck Analysis

- **L1 Drafter (kimi-k2.6):** ~430-540s per story (~4-5 min per candidate). Dominates pipeline time.
- **L2 Editorial (kimi-k2.6):** 271.62s for 6-point batch.
- **L2 Judge (glm-5.1:cloud):** ~10-15s per point, 6 points = ~86s total.
- **Embeddings (nomic-embed-text local):** 0.90s for 6 points. Negligible.
- **Structural validation / QnA / prober:** Sub-second each.

**Conclusion:** The pipeline is LLM-bound, not I/O or embedding-bound. Total time is acceptable for a one-time per-story generation workflow.

---

### Verification Results

✅ All assertions passed:
- 6 L1 points archived (status=draft, parent linkage preserved)
- 6 L2 points approved (status=approved, parent_point_id linked to L1)
- 0 orphaned L1 drafts remaining

---

### Files Involved

- `test_pipeline.py` — orchestrator
- `src/cv_weaver/generator/batch_editor.py` — L2 Batch Editor
- `src/cv_weaver/generator/engine.py` — L1 Generator
- `src/cv_weaver/utils/sanitizer.py` — Text sanitizer
- `src/cv_weaver/llm_client/embedder.py` — Local embedder
- `src/cv_weaver/llm_client/instructor_wrapper.py` — LLM client
- `src/cv_weaver/config.py` — Config (Component 5 commented out)

### Status: ✅ PASSED — Components 1-3 fully verified end-to-end.
