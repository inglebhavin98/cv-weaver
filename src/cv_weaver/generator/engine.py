"""Generator Engine: L1 per-story extraction + QnA refinement loop.

Orchestrates the full L1 pipeline for a single experience or project file:
1. Parse markdown → stories
2. Per-story: drafter → candidates
3. Per-candidate: validation → QnA loop → judge → save to DB

The QnA loop is human-in-the-loop: the system detects a flaw, asks the user
a targeted question, receives an answer, calls the refiner LLM, and repeats
until validation passes or max rounds reached.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from cv_weaver.config import Settings
from cv_weaver.generator.prompts import (
    CVPointCandidate,
    PointEvaluation,
    StoryExtraction,
    drafter_prompt,
    judge_prompt,
    refiner_prompt,
)
from cv_weaver.generator.validation_rules import RuleResult, POINT_LEVEL_RULES
from cv_weaver.knowledge_base.parser import ExperienceFile, Story, parse_file
from cv_weaver.llm_client.instructor_wrapper import LLMClient
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


# ─── Generator Engine ──────────────────────────────────────────────────


class GeneratorEngine:
    """Orchestrates L1 extraction, QnA refinement, and judge scoring."""

    def __init__(
        self,
        client: LLMClient,
        repo: CVPointRepository,
        settings: Settings,
        max_qna_rounds: int = 3,
    ):
        self._client = client
        self._repo = repo
        self._settings = settings
        self._max_qna_rounds = max_qna_rounds

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

        return GenerationResult(
            file_id=experience.file_id,
            story_results=story_results,
            total_points=total_points,
            total_qna_rounds=total_qna,
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

        current = candidate
        qna_rounds = 0
        converged = False

        # QnA refinement loop
        for round_num in range(self._max_qna_rounds):
            val_t0 = time.perf_counter()
            # Build a temporary CVPoint for validation
            temp_point = self._build_cvpoint(
                candidate=current,
                story=story,
                experience=experience,
                status=Status.DRAFT,
            )

            # Run deterministic validation
            violations = self._run_validation(temp_point)
            blocking = [v for v in violations if v.is_blocking]
            non_blocking = [v for v in violations if not v.is_blocking]
            val_elapsed = time.perf_counter() - val_t0
            print(f"    [CAND {candidate_index}] Validation: {len(blocking)} blocking, {len(non_blocking)} non-blocking in {val_elapsed:.3f}s")

            # If no blocking violations, we converge
            if not blocking:
                converged = True
                print(f"    [CAND {candidate_index}] Converged after {round_num} round(s)")
                break

            # Pick the first blocking violation as the focus of this round
            target = blocking[0]
            qna_rounds += 1

            # CLI interaction: present flaw + ask user
            print(f"\n    [QnA Round {qna_rounds}] {target.message}")
            if target.suggestion:
                print(f"    Suggestion: {target.suggestion}")
            user_answer = input("    Your response (or 'skip' to accept as-is): ").strip()

            if user_answer.lower() == "skip":
                # User declines to fix this blocking rule — mark as converged anyway
                converged = True
                print(f"    [CAND {candidate_index}] User skipped QnA")
                break

            # Refiner LLM call
            ref_t0 = time.perf_counter()
            refiner_prompt_text = refiner_prompt(
                previous_candidate=current,
                flaw_description=f"{target.name}: {target.message}",
                user_answer=user_answer,
                context_paragraph=experience.context_paragraph,
            )
            from cv_weaver.generator.prompts import RefinedPoint
            refined: RefinedPoint = self._client.chat_completion(
                prompt=refiner_prompt_text,
                response_model=RefinedPoint,
            )
            ref_elapsed = time.perf_counter() - ref_t0
            print(f"    [CAND {candidate_index}] Refiner done in {ref_elapsed:.2f}s")
            current = refined.refined

        # Judge scoring (after QnA convergence, regardless of whether it was skipped)
        judge_t0 = time.perf_counter()
        judge_prompt_text = judge_prompt(
            candidate=current,
            story_title=story.title,
        )
        evaluation: PointEvaluation = self._client.chat_completion(
            prompt=judge_prompt_text,
            response_model=PointEvaluation,
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
        print(f"    [CAND {candidate_index}] ◄── Total {total_elapsed:.2f}s (qna={qna_rounds} converged={converged})")

        return CandidateResult(
            point=final_point,
            evaluation=evaluation,
            qna_rounds=qna_rounds,
            converged=converged,
        )

    # ─── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _run_validation(point: CVPoint) -> List[RuleResult]:
        """Run all point-level validation rules and return failures."""
        failures = []
        for rule in POINT_LEVEL_RULES:
            result = rule(point)
            if not result.passed:
                failures.append(result)
        return failures

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
