"""L2 Batch Editor: deduplicate, merge, and finalize L1 draft points for a single company.

Operates on all L1 DRAFT points for a given file_id:
1. FETCH   — retrieve L1 draft points from the DB
2. EMBED   — compute embeddings (batch) for pairwise similarity
3. FLAG    — flag merge candidate pairs with cosine similarity > 0.85
4. EDIT    — Editorial LLM decides keep / merge / split / drop per point
5. JUDGE   — sanitize bullets + run the L1 Judge LLM for fresh scores
6. SAVE    — persist as generation_level='l2', status='approved'
7. CLEANUP — archive the original L1 drafts so they are not re-processed

This is the REAL Level 2. It does NOT read job descriptions, do RAG against
JDs, or inject keywords. That is Component 4 (the JD Customizer), which is
currently quarantined in `src/cv_weaver/customizer/` and out of scope.
"""

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

from cv_weaver.config import Settings
from cv_weaver.generator.prompts import (
    CVPointCandidate,
    JUDGE_SYSTEM_PROMPT,
    PointEvaluation,
    RefinedPoint,
    judge_prompt,
    refiner_prompt,
)
from cv_weaver.generator.validation_rules import POINT_LEVEL_RULES, RuleResult
from cv_weaver.llm_client.embedder import EmbedderClient
from cv_weaver.llm_client.instructor_wrapper import LLMClient
from cv_weaver.models.enums import ClassificationType, GenerationLevel, Status
from cv_weaver.models.schemas import (
    Classification,
    CVPoint,
    ExtendedContext,
    PointComponents,
    PointMetadata,
    PointScores,
    SourceContext,
)
from cv_weaver.storage.embeddings import _cosine_similarity, _vector_to_blob
from cv_weaver.storage.repository import CVPointRepository
from cv_weaver.utils.sanitizer import sanitize_for_machine_parsers


# ─── Response Models ───────────────────────────────────────────────────

class PointAction(BaseModel):
    """Single editorial decision for one or more L1 points.

    editorial_reasoning is declared FIRST to force Chain-of-Thought:
    the LLM must reason before it selects an action.
    """

    editorial_reasoning: str = Field(
        description=(
            "Step-by-step reasoning: you MUST explain your reasoning here FIRST, "
            "before outputting the action or any new point. Describe the overlap, "
            "gap, or strength that led to this decision."
        )
    )
    action: str = Field(
        description="Editorial action: keep or drop."
    )
    target_l1_ids: List[str] = Field(
        description="IDs of the L1 points this action applies to."
    )
    new_cv_point: Optional[CVPointCandidate] = Field(
        default=None,
        description="DEPRECATED: always null. The L2 editor only keeps or drops existing L1 points.",
    )


class BatchEditorOutput(BaseModel):
    """Response model for the L2 Batch Editor LLM."""

    point_actions: List[PointAction] = Field(
        description="Ordered list of editorial decisions for the batch."
    )


# ─── Dataclasses for Pipeline Results ────────────────────────────────────

@dataclass(frozen=True)
class BatchEditorResult:
    """Outcome of the L2 batch editor for one file_id."""

    file_id: str
    points_in: int
    points_out: int
    actions: List[PointAction]
    saved_points: List[CVPoint]
    total_llm_latency_s: float


# ─── Editorial LLM System Prompt ─────────────────────────────────────────

EDITORIAL_SYSTEM_PROMPT: str = """You are a senior technical editor reviewing a batch of resume bullet points extracted from a single work experience.

Your job is to ensure the final set of bullets is:
- NON-REDUNDANT: no two bullets should describe the same accomplishment
- COMPLETE: every significant accomplishment from the source material is represented
- CONCISE: drop weak or filler bullets that add no distinct value
- WELL-FORMED: each bullet starts with a strong past-tense verb, has metrics, and is under 200 chars

CRITICAL: Your role is REVIEW and SELECT, not REWRITE. You may only KEEP a point as-is or DROP it entirely. You do NOT create new bullets, merge bullets, or split bullets. The L1 drafter already produced the best possible bullets; your job is to curate which ones make the final cut.

CRITICAL INSTRUCTION: For every PointAction, you MUST explain your reasoning step-by-step in the 'editorial_reasoning' field BEFORE outputting the action. The reasoning must come first in your thought process.
"""


# ─── Prompt Builder ──────────────────────────────────────────────────────

def editorial_prompt(
    l1_points: List[CVPoint],
    merge_candidates: List[Tuple[CVPoint, CVPoint, float]],
) -> str:
    """Build the L2 Batch Editor prompt.

    Lists every L1 draft point, then appends mathematically flagged merge
    candidate pairs. The LLM returns a BatchEditorOutput with PointActions.
    """
    points_block = "\n\n".join(
        f"ID: {p.id}\n"
        f"  bullet: {p.rendered_bullet}\n"
        f"  verb: {p.components.action_verb}\n"
        f"  context: {p.components.context}\n"
        f"  result: {p.components.result}\n"
        f"  metrics: {', '.join(p.metadata.impact_metrics) or 'none'}\n"
        f"  skills: {', '.join(p.metadata.skills_utilized) or 'none'}\n"
        f"  situation: {p.extended_context.situation}\n"
        f"  task: {p.extended_context.task}"
        for p in l1_points
    )

    if merge_candidates:
        merge_block = "\n\n".join(
            f"MATH FLAG — similarity {sim:.3f}:\n"
            f"  Point A [{a.id}]: {a.rendered_bullet}\n"
            f"  Point B [{b.id}]: {b.rendered_bullet}\n"
            f"  Shared skills: {set(a.metadata.skills_utilized) & set(b.metadata.skills_utilized)}\n"
            f"  Shared metrics: {set(a.metadata.impact_metrics) & set(b.metadata.impact_metrics)}"
            for a, b, sim in merge_candidates
        )
    else:
        merge_block = "No merge candidates flagged by similarity analysis."

    return f"""## L1 Draft Points

{points_block}

## Merge Candidate Pairs (mathematically flagged)

{merge_block}

## Editorial Rules

1. **keep** — Use when a point is strong, distinct, and needs no change.
2. **drop** — Use when a point is weak, redundant, or adds no value compared to others.

You do NOT merge, split, rewrite, or create new bullets. Only keep or drop existing ones.

**Constraints:**
- Every significant accomplishment must be represented in the final set.
- No two final bullets should share the same core accomplishment.
- Max 8 points total for a single experience entry.
- Each final bullet must start with a strong past-tense verb, contain metrics, and be under 200 chars.

## Output
Return a JSON object matching the BatchEditorOutput schema with a list of PointAction objects. For each action, provide step-by-step reasoning first.
"""


# ─── Batch Editor Engine ─────────────────────────────────────────────────

class BatchEditorEngine:
    """Orchestrates L2 batch finalization for a single experience file."""

    def __init__(
        self,
        llm_client: LLMClient,
        embedder: EmbedderClient,
        repo: CVPointRepository,
        settings: Settings,
        similarity_threshold: float = 0.85,
    ):
        self._llm = llm_client
        self._embedder = embedder
        self._repo = repo
        self._settings = settings
        self._similarity_threshold = similarity_threshold

    # ─── Public API ────────────────────────────────────────────────────────

    def finalize_file(self, file_id: str) -> BatchEditorResult:
        """Run the full L2 Batch Editor pipeline on one file_id.

        Args:
            file_id: The source file identifier (e.g. `01_tata-neu`).

        Returns:
            BatchEditorResult with all saved L2 approved points.
        """
        t0 = time.perf_counter()
        total_llm_latency = 0.0

        # 1. FETCH
        all_points = self._repo.list_by_source(file_id)
        l1_points: List[CVPoint] = [
            p
            for p in all_points
            if p.generation_level == GenerationLevel.L1 and p.classification.status == Status.DRAFT
        ]
        print(f"[L2-BATCH] Fetched {len(l1_points)} L1 draft point(s) for {file_id}")

        if not l1_points:
            print("[L2-BATCH] No L1 draft points found. Nothing to finalize.")
            return BatchEditorResult(
                file_id=file_id,
                points_in=0,
                points_out=0,
                actions=[],
                saved_points=[],
                total_llm_latency_s=0.0,
            )

        # 2. EMBED (batch call for efficiency)
        # If embedding model is unavailable, gracefully fall back to rule-based
        # deduplication so the pipeline still works.
        flagged: List[Tuple[CVPoint, CVPoint, float]] = []
        try:
            embed_t0 = time.perf_counter()
            bullets = [p.rendered_bullet for p in l1_points]
            vectors = self._embedder.embed_batch(bullets)
            embeddings: dict[str, list[float]] = {}
            for p, vec in zip(l1_points, vectors):
                embeddings[p.id] = vec
                self._repo.update_embedding(p.id, _vector_to_blob(vec))
            print(
                f"[L2-BATCH] Embedded {len(l1_points)} point(s) in "
                f"{time.perf_counter() - embed_t0:.2f}s"
            )

            # 3. MATH FLAGGER — pairwise cosine similarity
            for i in range(len(l1_points)):
                for j in range(i + 1, len(l1_points)):
                    a, b = l1_points[i], l1_points[j]
                    sim = _cosine_similarity(embeddings[a.id], embeddings[b.id])
                    if sim > self._similarity_threshold:
                        flagged.append((a, b, sim))
            print(f"[L2-BATCH] Flagged {len(flagged)} merge candidate pair(s)")
        except Exception as exc:
            print(
                f"[L2-BATCH] Embedding failed ({type(exc).__name__}: {exc}). "
                "Falling back to rule-based deduplication."
            )
            flagged = self._rule_based_merge_flags(l1_points)
            print(f"[L2-BATCH] Rule-based flags: {len(flagged)} pair(s)")

        # 4. EDITORIAL LLM
        ed_t0 = time.perf_counter()
        prompt = editorial_prompt(l1_points, flagged)
        output: BatchEditorOutput = self._llm.chat_completion(
            prompt=prompt,
            response_model=BatchEditorOutput,
            system_prompt=EDITORIAL_SYSTEM_PROMPT,
        )
        ed_elapsed = time.perf_counter() - ed_t0
        total_llm_latency += ed_elapsed
        print(
            f"[L2-BATCH] Editorial LLM returned {len(output.point_actions)} action(s) "
            f"in {ed_elapsed:.2f}s"
        )

        # ── Interactive Approval: print plan and ask user ────────────────
        self._print_editorial_plan(output.point_actions, l1_points)
        approval = input("Approve and commit these L2 changes? [y/n]: ").strip().lower()
        if approval != "y":
            print("[L2-BATCH] User declined. Aborting — no changes saved or archived.")
            return BatchEditorResult(
                file_id=file_id,
                points_in=len(l1_points),
                points_out=0,
                actions=output.point_actions,
                saved_points=[],
                total_llm_latency_s=total_llm_latency,
            )

        # 5. JUDGE & SANITIZE each surviving point
        saved_points: List[CVPoint] = []
        for action in output.point_actions:
            if action.action == "drop":
                print(
                    f"[L2-BATCH] DROP ids={action.target_l1_ids} — "
                    f"{action.editorial_reasoning[:80]}..."
                )
                continue

            if action.action not in ("keep", "drop"):
                print(
                    f"[L2-BATCH] SKIP ids={action.target_l1_ids} — "
                    f"unsupported action '{action.action}' (L2 editor only supports keep/drop)"
                )
                continue

            final_point = self._build_final_point(action, l1_points)
            if final_point is None:
                print(
                    f"[L2-BATCH] SKIP ids={action.target_l1_ids} — "
                    "could not build point from action"
                )
                continue

            # Sanitize for machine parsers (ATS, YAML, LaTeX)
            final_point.rendered_bullet = sanitize_for_machine_parsers(
                final_point.rendered_bullet
            )
            final_point.components.result = sanitize_for_machine_parsers(
                final_point.components.result
            )
            final_point.components.context = sanitize_for_machine_parsers(
                final_point.components.context
            )

            # Run the exact same L1 Judge LLM for fresh scores
            j_t0 = time.perf_counter()
            candidate = CVPointCandidate(
                extended_context_situation=final_point.extended_context.situation,
                extended_context_task=final_point.extended_context.task,
                action_verb=final_point.components.action_verb,
                context=final_point.components.context,
                result=final_point.components.result,
                rendered_bullet=final_point.rendered_bullet,
                impact_metrics=final_point.metadata.impact_metrics,
                skills_utilized=final_point.metadata.skills_utilized,
                domain_tags=final_point.classification.domain_tags,
            )
            judge_prompt_text = judge_prompt(
                candidate=candidate,
                story_title=f"Batch finalization for {file_id}",
            )
            evaluation: PointEvaluation = self._llm.chat_completion(
                prompt=judge_prompt_text,
                response_model=PointEvaluation,
                system_prompt=JUDGE_SYSTEM_PROMPT,
                model=self._settings.judge_model,
            )
            j_elapsed = time.perf_counter() - j_t0
            total_llm_latency += j_elapsed

            final_point.scores = PointScores(
                impact_score=evaluation.impact_score,
                ats_score=evaluation.ats_score,
                completeness_score=evaluation.completeness_score,
            )

            print(
                f"[L2-BATCH] JUDGE {final_point.id[:8]}... "
                f"impact={evaluation.impact_score} ats={evaluation.ats_score} "
                f"complete={evaluation.completeness_score} in {j_elapsed:.2f}s"
            )

            # 6. SAVE — generation_level='l2', status='approved'
            final_point.classification.status = Status.APPROVED
            final_point.generation_level = GenerationLevel.L2
            self._repo.insert(final_point)
            saved_points.append(final_point)

            parent_snip = (
                final_point.classification.parent_point_id[:8]
                if final_point.classification.parent_point_id
                else "none"
            )
            print(
                f"[L2-BATCH] SAVED {final_point.id[:8]}... "
                f"action={action.action} parent={parent_snip} "
                f"bullet={final_point.rendered_bullet[:70]}..."
            )

        # 7. CLEANUP — archive original L1 drafts so they are not re-processed
        for p in l1_points:
            self._repo.update_status(p.id, Status.ARCHIVED)
        print(f"[L2-BATCH] Archived {len(l1_points)} original L1 draft(s)")

        total_elapsed = time.perf_counter() - t0
        print(
            f"[L2-BATCH] Done. {len(saved_points)} point(s) saved. "
            f"Total time: {total_elapsed:.2f}s (LLM: {total_llm_latency:.2f}s)"
        )

        return BatchEditorResult(
            file_id=file_id,
            points_in=len(l1_points),
            points_out=len(saved_points),
            actions=output.point_actions,
            saved_points=saved_points,
            total_llm_latency_s=total_llm_latency,
        )

    # ─── Interactive Approval ────────────────────────────────────────────

    @staticmethod
    def _print_editorial_plan(
        actions: List[PointAction],
        l1_points: List[CVPoint],
    ) -> None:
        """Print a clean CLI summary of the editorial plan before committing."""
        print()
        print("─" * 60)
        print("EDITORIAL PLAN — Review before committing")
        print("─" * 60)

        l1_by_id = {p.id: p for p in l1_points}

        for idx, action in enumerate(actions, start=1):
            bullet_preview = ""
            if action.action == "keep" and action.target_l1_ids:
                orig = l1_by_id.get(action.target_l1_ids[0])
                if orig:
                    bullet_preview = f" → keep '{orig.rendered_bullet[:60]}...'"
            elif action.action == "drop" and action.target_l1_ids:
                orig = l1_by_id.get(action.target_l1_ids[0])
                if orig:
                    bullet_preview = f" → DROP '{orig.rendered_bullet[:60]}...'"

            print(f"\n{idx}. [{action.action.upper()}] ids={action.target_l1_ids}")
            print(f"   Reason: {action.editorial_reasoning[:120]}...")
            if bullet_preview:
                print(f"   {bullet_preview}")

        print()
        print("─" * 60)

    # ─── Structural Validation & Auto-Refiner ────────────────────────────

    def _auto_refiner_fix(
        self,
        candidate: CVPointCandidate,
        blocking: List[RuleResult],
        source_l1: CVPoint,
    ) -> CVPointCandidate:
        """Send a merge/split candidate through the Refiner LLM to fix blocking flaws.

        Retries up to 2 times. Returns the best candidate achieved.
        """
        current = candidate
        for attempt in range(1, 3 + 1):
            if not blocking:
                return current

            target = blocking[0]
            flaw = f"{target.name}: {target.message}"
            directive = (
                f"Fix the structural flaw described above. "
                f"Do not add new content; only fix the formatting/grammar issue. "
                f"Preserve all existing metrics and skills."
            )

            ref_t0 = time.perf_counter()
            ref_prompt = refiner_prompt(
                previous_candidate=current,
                flaw_description=flaw,
                user_answer=directive,
                context_paragraph=None,
                prior_clarifications=[f"Auto-fix attempt {attempt}: {flaw}"],
            )
            refined: RefinedPoint = self._llm.chat_completion(
                prompt=ref_prompt,
                response_model=RefinedPoint,
            )
            elapsed = time.perf_counter() - ref_t0
            print(
                f"    [L2-BATCH] Auto-refiner attempt {attempt} done in {elapsed:.2f}s — "
                f"{refined.what_changed[:80]}..."
            )
            current = refined.refined

            # Re-validate
            temp_point = self._candidate_to_temp_cvpoint(current, source_l1)
            violations = [rule(temp_point) for rule in POINT_LEVEL_RULES]
            blocking = [v for v in violations if not v.passed and v.is_blocking]

        return current

    @staticmethod
    def _candidate_to_temp_cvpoint(
        candidate: CVPointCandidate,
        source_l1: CVPoint,
    ) -> CVPoint:
        """Build a throwaway CVPoint wrapper for rule validation."""
        return CVPoint(
            id="temp",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            source=SourceContext(
                file_id=source_l1.source.file_id,
                experience_type=source_l1.source.experience_type,
                raw_dump_excerpt=source_l1.source.raw_dump_excerpt,
            ),
            extended_context=ExtendedContext(
                situation=candidate.extended_context_situation,
                task=candidate.extended_context_task,
            ),
            components=PointComponents(
                action_verb=candidate.action_verb,
                context=candidate.context,
                result=candidate.result,
            ),
            rendered_bullet=candidate.rendered_bullet,
            metadata=PointMetadata(
                impact_metrics=candidate.impact_metrics,
                skills_utilized=candidate.skills_utilized,
            ),
            classification=Classification(
                type=ClassificationType.GENERAL,
                domain_tags=candidate.domain_tags,
                target_jd_id=None,
                status=Status.DRAFT,
                parent_point_id=None,
            ),
            scores=PointScores(impact_score=0, ats_score=0, completeness_score=0),
            generation_level=GenerationLevel.L2,
        )

    # ─── Rule-Based Fallback (when embedder is unavailable) ─────────────

    @staticmethod
    def _rule_based_merge_flags(
        l1_points: List[CVPoint],
    ) -> List[Tuple[CVPoint, CVPoint, float]]:
        """Flag potential merge candidates without embeddings.

        Uses heuristics:
        - Same action verb → high overlap signal
        - Jaccard similarity of skills > 0.5
        - Overlapping metrics
        """
        flagged: List[Tuple[CVPoint, CVPoint, float]] = []
        for i in range(len(l1_points)):
            for j in range(i + 1, len(l1_points)):
                a, b = l1_points[i], l1_points[j]
                score = 0.0

                # Same verb
                if a.components.action_verb.lower() == b.components.action_verb.lower():
                    score += 0.40

                # Skills overlap (Jaccard)
                skills_a = set(a.metadata.skills_utilized)
                skills_b = set(b.metadata.skills_utilized)
                if skills_a and skills_b:
                    intersection = len(skills_a & skills_b)
                    union = len(skills_a | skills_b)
                    jaccard = intersection / union if union else 0.0
                    if jaccard >= 0.5:
                        score += 0.35

                # Metrics overlap
                metrics_a = set(a.metadata.impact_metrics)
                metrics_b = set(b.metadata.impact_metrics)
                if metrics_a and metrics_b and (metrics_a & metrics_b):
                    score += 0.25

                if score >= 0.70:
                    flagged.append((a, b, min(score, 0.99)))
        return flagged

    # ─── Internal Helpers ────────────────────────────────────────────────

    def _build_final_point(
        self,
        action: PointAction,
        l1_points: List[CVPoint],
    ) -> Optional[CVPoint]:
        """Build a final CVPoint from an editorial action (keep only)."""
        if not action.target_l1_ids:
            return None

        if action.action == "keep":
            target_id = action.target_l1_ids[0]
            l1 = next((p for p in l1_points if p.id == target_id), None)
            if l1 is None:
                return None
            return self._clone_as_l2(l1, parent_id=l1.id)

        return None

    @staticmethod
    def _clone_as_l2(l1: CVPoint, parent_id: str) -> CVPoint:
        """Clone an L1 point into a new L2 point with a parent link."""
        now = datetime.now(timezone.utc)
        return CVPoint(
            id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
            source=l1.source,
            extended_context=l1.extended_context,
            components=l1.components,
            rendered_bullet=l1.rendered_bullet,
            metadata=l1.metadata,
            classification=Classification(
                type=ClassificationType.GENERAL,
                domain_tags=l1.classification.domain_tags,
                target_jd_id=None,
                status=Status.DRAFT,  # flipped to APPROVED after judge
                parent_point_id=parent_id,
            ),
            scores=PointScores(impact_score=0, ats_score=0, completeness_score=0),
            generation_level=GenerationLevel.L2,
        )

    @staticmethod
    def _candidate_to_l2(
        candidate: CVPointCandidate,
        parent_id: str,
        source_l1: CVPoint,
    ) -> CVPoint:
        """Convert a CVPointCandidate (from merge/split) into a full L2 CVPoint."""
        now = datetime.now(timezone.utc)
        return CVPoint(
            id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
            source=SourceContext(
                file_id=source_l1.source.file_id,
                experience_type=source_l1.source.experience_type,
                raw_dump_excerpt=source_l1.source.raw_dump_excerpt,
            ),
            extended_context=ExtendedContext(
                situation=candidate.extended_context_situation,
                task=candidate.extended_context_task,
            ),
            components=PointComponents(
                action_verb=candidate.action_verb,
                context=candidate.context,
                result=candidate.result,
            ),
            rendered_bullet=candidate.rendered_bullet,
            metadata=PointMetadata(
                impact_metrics=candidate.impact_metrics,
                skills_utilized=candidate.skills_utilized,
            ),
            classification=Classification(
                type=ClassificationType.GENERAL,
                domain_tags=candidate.domain_tags,
                target_jd_id=None,
                status=Status.DRAFT,
                parent_point_id=parent_id,
            ),
            scores=PointScores(impact_score=0, ats_score=0, completeness_score=0),
            generation_level=GenerationLevel.L2,
        )
