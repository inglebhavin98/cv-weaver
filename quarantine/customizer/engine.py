"""Customizer Engine: L2 JD-aware point rewriting + selection.

Orchestrates the L2 pipeline for a single Job Description:
1. Analyze JD → structured requirements
2. Embed JD + search approved L1 points via RAG
3. Rewrite top-K retrieved points to align with JD
4. Select final subset (deduplication + coverage)
5. Save L2 points to DB with parent links

The engine is fully debuggable: every step prints timing and intermediate
results so failures can be pinpointed.
"""

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from cv_weaver.config import Settings
from cv_weaver.customizer.prompts import (
    JDAnalysis,
    JDRequirement,
    PointSelection,
    RewrittenPoint,
    jd_analysis_prompt,
    point_rewriter_prompt,
    selection_prompt,
)
from cv_weaver.generator.prompts import CVPointCandidate
from cv_weaver.llm_client.embedder import EmbedderClient
from cv_weaver.llm_client.instructor_wrapper import LLMClient
from cv_weaver.models.enums import ClassificationType, GenerationLevel, Status
from cv_weaver.models.schemas import Classification, CVPoint, ExtendedContext, PointComponents, PointMetadata, PointScores, SourceContext
from cv_weaver.storage.embeddings import EmbeddingIndex
from cv_weaver.storage.repository import CVPointRepository


# ─── Dataclasses for Pipeline Results ──────────────────────────────────

@dataclass(frozen=True)
class RewrittenCandidate:
    """Outcome of rewriting one L1 point for a JD."""

    parent_point: CVPoint
    rewritten: CVPointCandidate
    jd_alignment_score: int
    keywords_injected: List[str]
    metrics_preserved: bool
    what_changed: str
    llm_latency_s: float


@dataclass(frozen=True)
class CustomizationResult:
    """Outcome of the full L2 pipeline for one JD."""

    jd_analysis: JDAnalysis
    total_l1_points_searched: int
    points_rewritten: int
    points_selected: int
    selected_points: List[CVPoint]
    coverage_score: int
    total_llm_latency_s: float


# ─── Customizer Engine ─────────────────────────────────────────────────

class CustomizerEngine:
    """Orchestrates L2 JD analysis, RAG retrieval, rewriting, and selection."""

    def __init__(
        self,
        llm_client: LLMClient,
        embedder: EmbedderClient,
        repo: CVPointRepository,
        index: EmbeddingIndex,
        settings: Settings,
        similarity_threshold: float = 0.65,
        max_points_to_rewrite: int = 15,
        max_points_per_selection: int = 8,
    ):
        self._llm = llm_client
        self._embedder = embedder
        self._repo = repo
        self._index = index
        self._settings = settings
        self._similarity_threshold = similarity_threshold
        self._max_points_to_rewrite = max_points_to_rewrite
        self._max_points_per_selection = max_points_per_selection

    # ─── Public API ──────────────────────────────────────────────────────

    def customize_for_jd(self, jd_text: str, top_k: int = 15) -> CustomizationResult:
        """Run the full L2 pipeline on one Job Description.

        Args:
            jd_text: The raw job description text.
            top_k: Number of L1 points to retrieve via RAG.

        Returns:
            CustomizationResult with selected L2 CVPoints saved to the DB.
        """
        pipeline_t0 = time.perf_counter()
        total_llm_latency = 0.0

        # 1. JD Analysis
        jd_t0 = time.perf_counter()
        print(f"\n[L2] ──► JD Analysis (model={self._llm._model})")
        jd_analysis = self._analyze_jd(jd_text)
        jd_elapsed = time.perf_counter() - jd_t0
        total_llm_latency += jd_elapsed
        print(
            f"[L2] ◄── JD Analysis done in {jd_elapsed:.2f}s | "
            f"role='{jd_analysis.role_title}' requirements={len(jd_analysis.key_requirements)}"
        )

        # 2. Embed JD + RAG Search
        rag_t0 = time.perf_counter()
        print(f"\n[L2] ──► RAG Search (top_k={top_k}, threshold={self._similarity_threshold})")
        jd_vector = self._embedder.embed(jd_text)
        retrieved = self._index.search(jd_vector, top_k=top_k)
        # Filter by similarity threshold
        retrieved = [r for r in retrieved if r[1] >= self._similarity_threshold]
        print(
            f"[L2] ◄── RAG done in {time.perf_counter() - rag_t0:.2f}s | "
            f"retrieved {len(retrieved)} point(s) above threshold"
        )

        if not retrieved:
            print("[L2] ⚠ No L1 points matched the JD. Nothing to rewrite.")
            return CustomizationResult(
                jd_analysis=jd_analysis,
                total_l1_points_searched=0,
                points_rewritten=0,
                points_selected=0,
                selected_points=[],
                coverage_score=0,
                total_llm_latency_s=total_llm_latency,
            )

        # 3. Rewriting
        rewrite_t0 = time.perf_counter()
        print(f"\n[L2] ──► Rewriting {min(len(retrieved), self._max_points_to_rewrite)} point(s)")
        rewritten_candidates: List[RewrittenCandidate] = []
        for idx, (point, similarity) in enumerate(retrieved[: self._max_points_to_rewrite], start=1):
            cand_t0 = time.perf_counter()
            print(f"\n  [REWRITE {idx}/{min(len(retrieved), self._max_points_to_rewrite)}] id={point.id[:8]}... sim={similarity:.3f}")
            print(f"  original: {point.rendered_bullet[:80]}...")

            l1_candidate = self._cvpoint_to_candidate(point)
            rw_result = self._rewrite_point(l1_candidate, jd_analysis, point.rendered_bullet)
            rw_elapsed = time.perf_counter() - cand_t0
            total_llm_latency += rw_elapsed

            print(
                f"  rewritten: {rw_result.refined.rendered_bullet[:80]}... | "
                f"alignment={rw_result.jd_alignment_score} metrics_preserved={rw_result.metrics_preserved} "
                f"in {rw_elapsed:.2f}s"
            )

            rewritten_candidates.append(
                RewrittenCandidate(
                    parent_point=point,
                    rewritten=rw_result.refined,
                    jd_alignment_score=rw_result.jd_alignment_score,
                    keywords_injected=rw_result.keywords_injected,
                    metrics_preserved=rw_result.metrics_preserved,
                    what_changed=rw_result.what_changed,
                    llm_latency_s=rw_elapsed,
                )
            )
        print(
            f"[L2] ◄── Rewriting done in {time.perf_counter() - rewrite_t0:.2f}s | "
            f"rewrote {len(rewritten_candidates)} point(s)"
        )

        # 4. Selection
        select_t0 = time.perf_counter()
        print(f"\n[L2] ──► Selection (max={self._max_points_per_selection})")
        selection = self._select_points(rewritten_candidates, jd_analysis)
        select_elapsed = time.perf_counter() - select_t0
        total_llm_latency += select_elapsed
        print(
            f"[L2] ◄── Selection done in {select_elapsed:.2f}s | "
            f"selected={len(selection.selected_ids)} rejected={len(selection.rejection_reasons)} "
            f"coverage={selection.coverage_score}"
        )

        # 5. Build and save L2 CVPoints
        save_t0 = time.perf_counter()
        print(f"\n[L2] ──► Saving L2 points to DB")
        selected_l2_points: List[CVPoint] = []
        for sel_id in selection.selected_ids:
            # Find the corresponding rewritten candidate
            match = next((rc for rc in rewritten_candidates if rc.parent_point.id == sel_id), None)
            if match is None:
                print(f"  [SAVE] ⚠ ID {sel_id[:8]}... not found in rewritten set — skipping")
                continue

            l2_point = self._build_l2_cvpoint(
                parent=match.parent_point,
                candidate=match.rewritten,
                jd_analysis=jd_analysis,
            )
            self._repo.insert(l2_point)
            selected_l2_points.append(l2_point)
            print(f"  [SAVE] {l2_point.id[:8]}... parent={match.parent_point.id[:8]}... "
                  f"bullet='{l2_point.rendered_bullet[:70]}...'")

        save_elapsed = time.perf_counter() - save_t0
        total_elapsed = time.perf_counter() - pipeline_t0
        print(
            f"[L2] ◄── Saved {len(selected_l2_points)} L2 point(s) in {save_elapsed:.2f}s | "
            f"pipeline total={total_elapsed:.2f}s"
        )

        return CustomizationResult(
            jd_analysis=jd_analysis,
            total_l1_points_searched=len(retrieved),
            points_rewritten=len(rewritten_candidates),
            points_selected=len(selected_l2_points),
            selected_points=selected_l2_points,
            coverage_score=selection.coverage_score,
            total_llm_latency_s=total_llm_latency,
        )

    # ─── Internal Steps ────────────────────────────────────────────────────

    def _analyze_jd(self, jd_text: str) -> JDAnalysis:
        """Call the JD Analyzer LLM."""
        prompt = jd_analysis_prompt(jd_text)
        return self._llm.chat_completion(prompt=prompt, response_model=JDAnalysis)

    def _rewrite_point(
        self,
        l1_candidate: CVPointCandidate,
        jd_analysis: JDAnalysis,
        original_bullet: str,
    ) -> RewrittenPoint:
        """Call the Point Rewriter LLM."""
        prompt = point_rewriter_prompt(l1_candidate, jd_analysis, original_bullet)
        return self._llm.chat_completion(prompt=prompt, response_model=RewrittenPoint)

    def _select_points(
        self,
        candidates: List[RewrittenCandidate],
        jd_analysis: JDAnalysis,
    ) -> PointSelection:
        """Call the Selector LLM.

        If there are ≤ max_points_per_selection candidates, skip the LLM
        and select all (they're already filtered by RAG threshold).
        """
        if len(candidates) <= self._max_points_per_selection:
            # Fast path: no need to call LLM for trivial selection
            ids = [rc.parent_point.id for rc in candidates]
            return PointSelection(
                selected_ids=ids,
                rejection_reasons={},
                coverage_score=5,  # Neutral score; user can override
            )

        # Build a temporary ID map because the LLM works with indices
        # but we need to return real parent_point IDs.
        point_id_map = {i: rc.parent_point.id for i, rc in enumerate(candidates)}
        rewritten_points = [rc.rewritten for rc in candidates]

        prompt = selection_prompt(rewritten_points, jd_analysis, point_id_map)
        return self._llm.chat_completion(prompt=prompt, response_model=PointSelection)

    # ─── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _cvpoint_to_candidate(point: CVPoint) -> CVPointCandidate:
        """Convert a full CVPoint back into the flat candidate shape the LLM expects."""
        return CVPointCandidate(
            extended_context_situation=point.extended_context.situation,
            extended_context_task=point.extended_context.task,
            action_verb=point.components.action_verb,
            context=point.components.context,
            result=point.components.result,
            rendered_bullet=point.rendered_bullet,
            impact_metrics=point.metadata.impact_metrics,
            skills_utilized=point.metadata.skills_utilized,
            domain_tags=point.classification.domain_tags,
        )

    @staticmethod
    def _build_l2_cvpoint(
        parent: CVPoint,
        candidate: CVPointCandidate,
        jd_analysis: JDAnalysis,
    ) -> CVPoint:
        """Build a canonical L2 CVPoint from a rewritten candidate, linked to its L1 parent."""
        now = datetime.now(timezone.utc)
        return CVPoint(
            id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
            source=SourceContext(
                file_id=parent.source.file_id,
                experience_type=parent.source.experience_type,
                raw_dump_excerpt=parent.source.raw_dump_excerpt,
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
                type=ClassificationType.JD_SPECIFIC,
                domain_tags=candidate.domain_tags,
                target_jd_id=None,  # TODO: add JD hashing/ID system
                status=Status.DRAFT,
                parent_point_id=parent.id,
            ),
            scores=PointScores(
                impact_score=0,
                ats_score=0,
                completeness_score=0,
            ),
            generation_level=GenerationLevel.L2,
        )
