"""Generator Engine: L1 per-story extraction + QnA refinement loop.

Orchestrates the full L1 pipeline for a single experience or project file:
1. Parse markdown → stories
2. Per-story: drafter → candidates
3. Per-candidate: validation → QnA loop → judge → save to DB

The QnA loop is human-in-the-loop: the system detects a flaw, asks the user
a targeted question, receives an answer, calls the refiner LLM, and repeats
until validation passes or max rounds reached.
"""

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from cv_weaver.config import Settings
from cv_weaver.generator.prompts import (
    CVPointCandidate,
    JUDGE_SYSTEM_PROMPT,
    PointEvaluation,
    PROBER_SYSTEM_PROMPT,
    SemanticProberResult,
    StoryExtraction,
    drafter_prompt,
    judge_prompt,
    prober_prompt,
    refiner_prompt,
)
from cv_weaver.generator.validation_rules import RuleResult, POINT_LEVEL_RULES
from cv_weaver.knowledge_base.parser import ExperienceFile, Story, parse_file
from cv_weaver.llm_client.instructor_wrapper import LLMClient, LLMRetryError
from cv_weaver.models.enums import ClassificationType, ExperienceType, GenerationLevel, Status
from cv_weaver.models.schemas import Classification, CVPoint, ExtendedContext, PointComponents, PointMetadata, PointScores, SourceContext
from cv_weaver.storage.db import get_connection
from cv_weaver.storage.repository import CVPointRepository


# ─── Dataclasses for Pipeline Results ──────────────────────────────────

@dataclass(frozen=True)
class CandidateResult:
    """Outcome of processing one CVPoint candidate through the full L1 pipeline."""

    point: CVPoint
    evaluation: PointEvaluation
    qna_rounds: int
    semantic_rounds: int  # Count of semantic probing QnA rounds specifically
    converged: bool  # True if validation passed before max rounds


@dataclass(frozen=True)
class StoryResult:
    """Outcome of processing one story."""

    story_title: str
    candidates: List[CandidateResult]


@dataclass(frozen=True)
class GenerationResult:
    """Outcome of processing one experience / project file."""

    file_id: str
    story_results: List[StoryResult]
    total_points: int
    total_qna_rounds: int
    total_semantic_rounds: int


# ─── Generator Engine ──────────────────────────────────────────────────


class GeneratorEngine:
    """Orchestrates L1 extraction, QnA refinement, and judge scoring."""

    def __init__(
        self,
        client: LLMClient,
        repo: CVPointRepository,
        settings: Settings,
        max_qna_rounds: int = 3,
        max_semantic_rounds: int = 3,
    ):
        self._client = client
        self._repo = repo
        self._settings = settings
        self._max_qna_rounds = max_qna_rounds
        self._max_semantic_rounds = max_semantic_rounds

        # Prober result cache: key = hash(story_body + rendered_bullet + scope_summary)
        # Cuts redundant LLM calls when the same candidate is reprobed after a failed refiner.
        self._prober_cache: dict[str, SemanticProberResult] = {}

    def generate_from_file(self, file_path: str | Path, source_type: str) -> GenerationResult:
        """Run the full L1 pipeline on one knowledge base file.

        Args:
            file_path: Path to the `.md` file.
            source_type: "experience" or "project".

        Returns:
            GenerationResult with all processed points saved to the DB.
        """
        experience = parse_file(Path(file_path), source_type)
        story_results: List[StoryResult] = []

        for story in experience.stories:
            story_res = self._process_story(story, experience)
            story_results.append(story_res)

        total_points = sum(len(s.candidates) for s in story_results)
        total_qna = sum(sum(c.qna_rounds for c in s.candidates) for s in story_results)
        total_semantic = sum(sum(c.semantic_rounds for c in s.candidates) for s in story_results)

        return GenerationResult(
            file_id=experience.file_id,
            story_results=story_results,
            total_points=total_points,
            total_qna_rounds=total_qna,
            total_semantic_rounds=total_semantic,
        )

    # ─── Per-Story Processing ────────────────────────────────────────────

    def _process_story(self, story: Story, experience: ExperienceFile) -> StoryResult:
        """Run drafter → candidates → validation/QnA → judge → save."""
        story_t0 = time.perf_counter()
        print(f"\n  [STORY] ──► {story.title}")

        # 1. Drafter extraction
        drafter_t0 = time.perf_counter()
        prompt = drafter_prompt(
            story_title=story.title,
            story_body=story.body,
            story_skills=story.skills,
            story_metrics=story.metrics,
            story_team=story.team,
            story_role=story.role,
            context_paragraph=experience.context_paragraph,
        )
        extraction: StoryExtraction = self._client.chat_completion(
            prompt=prompt,
            response_model=StoryExtraction,
        )
        drafter_elapsed = time.perf_counter() - drafter_t0
        print(f"  [STORY] Drafter returned {len(extraction.candidates)} candidate(s) in {drafter_elapsed:.2f}s")

        # 2. Process each candidate
        candidate_results: List[CandidateResult] = []
        for idx, cand in enumerate(extraction.candidates, start=1):
            result = self._process_candidate(
                candidate=cand,
                story=story,
                experience=experience,
                candidate_index=idx,
            )
            candidate_results.append(result)

        story_elapsed = time.perf_counter() - story_t0
        print(f"  [STORY] ◄── {story.title} done in {story_elapsed:.2f}s ({len(candidate_results)} candidate(s))")
        return StoryResult(story_title=story.title, candidates=candidate_results)

    # ─── Per-Candidate Processing ──────────────────────────────────────

    def _process_candidate(
        self,
        candidate: CVPointCandidate,
        story: Story,
        experience: ExperienceFile,
        candidate_index: int = 1,
    ) -> CandidateResult:
        """Run validation → QnA loop → judge → save one candidate."""
        cand_t0 = time.perf_counter()
        print(f"\n    [CAND {candidate_index}] ──► bullet='{candidate.rendered_bullet[:60]}...'")
        if candidate.scope_summary:
            print(f"    [CAND {candidate_index}] scope: {candidate.scope_summary}")

        current = candidate
        qna_rounds = 0
        converged = False
        clarifications: List[str] = []
        # Track prober confidence trajectory for convergence heuristics
        prober_history: List[dict] = []
        # Track semantic QnA rounds separately from structural fixes
        semantic_rounds_done = 0

        # Two-phase QnA refinement loop
        for round_num in range(self._max_qna_rounds):
            # ── Phase 1: Structural Validation ──
            val_t0 = time.perf_counter()
            temp_point = self._build_cvpoint(
                candidate=current,
                story=story,
                experience=experience,
                status=Status.DRAFT,
            )
            violations = self._run_validation(temp_point)
            blocking = [v for v in violations if v.is_blocking]
            val_elapsed = time.perf_counter() - val_t0
            print(f"    [CAND {candidate_index}] Structural: {len(blocking)} blocking in {val_elapsed:.3f}s")

            if blocking:
                target = blocking[0]
                qna_rounds += 1
                print(f"\n    [Structural QnA Round {qna_rounds}] {target.message}")
                if target.suggestion:
                    print(f"    Suggestion: {target.suggestion}")
                user_answer = input("    Your response (or 'skip' to accept as-is): ").strip()

                if not user_answer or user_answer.lower() == "skip":
                    converged = True
                    print(f"    [CAND {candidate_index}] User skipped structural QnA")
                    break

                ref_t0 = time.perf_counter()
                refiner_prompt_text = refiner_prompt(
                    previous_candidate=current,
                    flaw_description=f"{target.name}: {target.message}",
                    user_answer=user_answer,
                    context_paragraph=experience.context_paragraph,
                    prior_clarifications=clarifications,
                )
                from cv_weaver.generator.prompts import RefinedPoint
                try:
                    refined: RefinedPoint = self._client.chat_completion(
                        prompt=refiner_prompt_text,
                        response_model=RefinedPoint,
                    )
                except LLMRetryError as exc:
                    print(f"    [CAND {candidate_index}] Refiner FAILED after {exc.attempts} attempts: {exc.last_error[:100]}")
                    print(f"    [CAND {candidate_index}] Keeping previous bullet unchanged. Your answer was saved for future rounds.")
                    clarifications.append(f"Structural fix ({target.name}): {user_answer} [refiner failed, kept previous]")
                    continue  # keep previous candidate, loop back
                print(f"    [CAND {candidate_index}] Refiner done in {time.perf_counter() - ref_t0:.2f}s")
                current = refined.refined
                print(f"    [CAND {candidate_index}] Refined bullet: {current.rendered_bullet}")
                clarifications.append(f"Structural fix ({target.name}): {user_answer}")
                continue  # loop back to re-validate structurally

            # ── Phase 2: Semantic round limit guard ──
            if semantic_rounds_done >= self._max_semantic_rounds:
                converged = True
                print(f"    [CAND {candidate_index}] Converged — max semantic rounds ({self._max_semantic_rounds}) reached")
                break

            # ── Phase 3: Semantic Prober ──
            probe_t0 = time.perf_counter()
            prober_result = self._run_semantic_probe(current, story)
            probe_elapsed = time.perf_counter() - probe_t0
            print(
                f"    [CAND {candidate_index}] Prober: gap={prober_result.has_semantic_gap} "
                f"confidence={prober_result.confidence} cats={prober_result.gap_categories} "
                f"in {probe_elapsed:.2f}s"
            )

            # Convergence heuristics: early-exit if we're not making meaningful progress
            if self._should_converge(prober_result, prober_history, round_num):
                converged = True
                print(f"    [CAND {candidate_index}] Converged after {round_num} round(s) — confidence plateau or minor remaining gaps")
                break

            if not prober_result.has_semantic_gap:
                converged = True
                print(f"    [CAND {candidate_index}] Converged after {round_num} round(s) — no semantic gaps")
                break

            prober_history.append({
                "confidence": prober_result.confidence,
                "gap_count": len(prober_result.gap_categories),
                "categories": prober_result.gap_categories.copy(),
            })

            # ── Phase 3: Semantic QnA ──
            qna_rounds += 1
            print(f"\n    [Semantic QnA Round {qna_rounds}] {prober_result.target_question}")
            print(f"    [Missing: {prober_result.what_is_missing}]")

            # User guidance: warn about common anti-patterns before they type
            self._print_user_guidance(prober_result)

            user_answer = input("    Your response (or 'skip' to accept as-is): ").strip()

            if user_answer.lower() == "skip":
                converged = True
                print(f"    [CAND {candidate_index}] User skipped semantic QnA")
                break

            semantic_rounds_done += 1

            # Extra guidance if user asks for multiple bullets
            if any(phrase in user_answer.lower() for phrase in ("two bullet", "2 bullet", "multiple bullet", "separate bullet", "output two", "output 2", "must now output two")):
                print(f"    ⚠️  WARNING: You asked for multiple bullets, but the refiner can only output ONE bullet at a time.")
                print(f"    ⚠️  Your request will likely be ignored or cause malformed output. Focus on improving the CURRENT bullet only.")

            ref_t0 = time.perf_counter()
            refiner_prompt_text = refiner_prompt(
                previous_candidate=current,
                flaw_description=f"Semantic gap ({', '.join(prober_result.gap_categories)}): {prober_result.what_is_missing}",
                user_answer=user_answer,
                context_paragraph=experience.context_paragraph,
                prior_clarifications=clarifications,
            )
            from cv_weaver.generator.prompts import RefinedPoint
            try:
                refined: RefinedPoint = self._client.chat_completion(
                    prompt=refiner_prompt_text,
                    response_model=RefinedPoint,
                )
            except LLMRetryError as exc:
                print(f"    [CAND {candidate_index}] Refiner FAILED after {exc.attempts} attempts: {exc.last_error[:100]}")
                print(f"    [CAND {candidate_index}] Keeping previous bullet unchanged. Your answer was saved for future rounds.")
                clarifications.append(f"Semantic fix ({', '.join(prober_result.gap_categories)}): {user_answer} [refiner failed, kept previous]")
                continue  # keep previous candidate, loop back
            print(f"    [CAND {candidate_index}] Refiner done in {time.perf_counter() - ref_t0:.2f}s")
            current = refined.refined
            print(f"    [CAND {candidate_index}] Refined bullet: {current.rendered_bullet}")
            clarifications.append(f"Semantic fix ({', '.join(prober_result.gap_categories)}): {user_answer}")
            # loop back to re-validate structurally + probe semantically

        # Judge scoring (after QnA convergence, regardless of whether it was skipped)
        judge_t0 = time.perf_counter()
        judge_prompt_text = judge_prompt(
            candidate=current,
            story_title=story.title,
            source_type=experience.source_type,
        )
        evaluation: PointEvaluation = self._client.chat_completion(
            prompt=judge_prompt_text,
            response_model=PointEvaluation,
            system_prompt=JUDGE_SYSTEM_PROMPT,
            model=self._settings.judge_model,
        )
        judge_elapsed = time.perf_counter() - judge_t0
        print(f"    [CAND {candidate_index}] Judge done in {judge_elapsed:.2f}s (impact={evaluation.impact_score} ats={evaluation.ats_score} complete={evaluation.completeness_score})")

        # Build final CVPoint with judge scores
        build_t0 = time.perf_counter()
        final_point = self._build_cvpoint(
            candidate=current,
            story=story,
            experience=experience,
            status=Status.DRAFT,
            scores=PointScores(
                impact_score=evaluation.impact_score,
                ats_score=evaluation.ats_score,
                completeness_score=evaluation.completeness_score,
            ),
        )

        # Save to DB
        self._repo.insert(final_point)
        db_elapsed = time.perf_counter() - build_t0
        print(f"    [CAND {candidate_index}] Build+DB save in {db_elapsed:.3f}s")

        total_elapsed = time.perf_counter() - cand_t0
        print(f"    [CAND {candidate_index}] ◄── Total {total_elapsed:.2f}s (qna={qna_rounds} semantic={semantic_rounds_done} converged={converged})")

        return CandidateResult(
            point=final_point,
            evaluation=evaluation,
            qna_rounds=qna_rounds,
            semantic_rounds=semantic_rounds_done,
            converged=converged,
        )

    # ─── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _should_converge(
        prober_result: SemanticProberResult,
        history: List[dict],
        round_num: int,
    ) -> bool:
        """Convergence heuristics to avoid burning LLM calls on diminishing returns.

        Returns True if we should accept the current draft and stop iterating.
        """
        # Heuristic 1: No gap at all
        if not prober_result.has_semantic_gap:
            return True

        # Heuristic 2: High confidence with few minor gaps — good enough
        if prober_result.confidence >= 8 and len(prober_result.gap_categories) <= 2:
            return True

        # Heuristic 3: Moving goalposts — prober finds DIFFERENT gaps after user fixes
        # This is the "whack-a-mole" pattern: fix business gaps, prober invents tech gaps.
        if len(history) >= 1:
            last = history[-1]
            current_cats = set(prober_result.gap_categories)
            last_cats = set(last["categories"])
            # If confidence is high and the gap categories shifted (not a strict subset),
            # the prober is just finding new things to complain about.
            if (
                prober_result.confidence >= 8
                and not current_cats.issubset(last_cats)
                and not last_cats.issubset(current_cats)
            ):
                return True

        # Heuristic 4: Confidence plateau — not improving across rounds
        if len(history) >= 2:
            last = history[-1]
            current_conf = prober_result.confidence
            if current_conf <= last["confidence"] and len(prober_result.gap_categories) >= last["gap_count"]:
                # Confidence not increasing and gap count not shrinking
                return True

        # Heuristic 5: Hard cap (round_num is 0-indexed)
        if round_num >= 2:  # Already did 3 rounds
            return True

        return False

    @staticmethod
    def _print_user_guidance(prober_result: SemanticProberResult) -> None:
        """Print preemptive guidance before the user types their answer."""
        # Warn about multi-bullet requests
        if any(cat in prober_result.gap_categories for cat in ("scope", "business", "strategic_intent")):
            print("    💡 Tip: Keep your answer focused on THIS bullet only. Do not ask for multiple bullets.")
        if "metrics" in prober_result.gap_categories:
            print("    💡 Tip: Provide the exact number, percentage, or time value. One metric is enough.")
        if "tech_stack" in prober_result.gap_categories:
            print("    💡 Tip: Name the specific technology, framework, or tool (e.g., 'React Context API' not 'caching layer').")

    @staticmethod
    def _run_validation(point: CVPoint) -> List[RuleResult]:
        """Run all point-level validation rules and return failures."""
        failures = []
        for rule in POINT_LEVEL_RULES:
            result = rule(point)
            if not result.passed:
                failures.append(result)
        return failures

    def _run_semantic_probe(
        self,
        candidate: CVPointCandidate,
        story: Story,
    ) -> SemanticProberResult:
        """Call the Semantic Prober LLM to compare draft against raw story.

        Uses the dedicated prober system prompt (PROBER_SYSTEM_PROMPT) to ensure
        the LLM stays strictly bounded to the audit checklist and does not
        hallucinate metrics or output conversational filler.

        Results are cached keyed by (story_body + rendered_bullet + scope_summary)
        to avoid redundant LLM calls when the refiner fails and the bullet doesn't change.
        """
        cache_key = hashlib.sha256(
            f"{story.body}::{candidate.rendered_bullet}::{candidate.scope_summary}".encode()
        ).hexdigest()
        if cache_key in self._prober_cache:
            print(f"    [PROBER] Cache hit — skipping LLM call")
            return self._prober_cache[cache_key]

        prompt = prober_prompt(
            story_title=story.title,
            story_body=story.body,
            candidate=candidate,
        )
        result: SemanticProberResult = self._client.chat_completion(
            prompt=prompt,
            response_model=SemanticProberResult,
            system_prompt=PROBER_SYSTEM_PROMPT,
        )
        self._prober_cache[cache_key] = result
        return result

    @staticmethod
    def _build_cvpoint(
        candidate: CVPointCandidate,
        story: Story,
        experience: ExperienceFile,
        status: Status,
        scores: Optional[PointScores] = None,
    ) -> CVPoint:
        """Wrap a CVPointCandidate into a full canonical CVPoint."""
        now = datetime.now(timezone.utc)
        return CVPoint(
            created_at=now,
            updated_at=now,
            source=SourceContext(
                file_id=experience.file_id,
                experience_type=ExperienceType(experience.source_type),
                raw_dump_excerpt=story.raw_text[:500],  # First 500 chars for traceability
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
                status=status,
                parent_point_id=None,
            ),
            scores=scores or PointScores(impact_score=0, ats_score=0, completeness_score=0),
            generation_level=GenerationLevel.L1,
        )
