"""Prompt templates and response models for the L2 Customizer Engine.

The Customizer takes approved L1 CV points and rewrites them to align with
a specific Job Description (JD). It uses RAG retrieval + LLM rewriting.

Three LLM roles:
1. JD Analyzer    — JD text → structured skill/requirement extraction
2. Point Rewriter — (L1 point + JD analysis) → rewritten CVPointCandidate
3. Selector       — (rewritten candidates + JD) → final selection + ranking

All prompts are plain strings. The caller injects them into
LLMClient.chat_completion along with the appropriate response_model.
"""

from typing import List

from pydantic import BaseModel, Field

from cv_weaver.generator.prompts import CVPointCandidate


# ─── Response Models for LLM Output ────────────────────────────────────

class JDRequirement(BaseModel):
    """One extracted requirement or skill from a Job Description."""

    category: str = Field(
        description="Category: 'hard_skill', 'soft_skill', 'domain', 'responsibility', 'nice_to_have'"
    )
    text: str = Field(description="The exact requirement text from the JD")
    priority: int = Field(
        ge=1,
        le=5,
        description="Priority: 5 = must-have, 1 = nice-to-have. Infer from language like 'required', 'preferred', 'bonus'.",
    )


class JDAnalysis(BaseModel):
    """Response model for the JD Analyzer."""

    role_title: str = Field(description="The job title being applied for")
    key_requirements: List[JDRequirement] = Field(
        description="Top 8–12 requirements extracted from the JD"
    )
    tone_keywords: List[str] = Field(
        description="Adjectives and verbs that describe the company's culture or expectations, e.g., 'fast-paced', 'collaborative', 'self-starter'"
    )
    must_have_skills: List[str] = Field(
        description="Skills explicitly marked as required or essential"
    )
    nice_to_have_skills: List[str] = Field(
        description="Skills marked as preferred, bonus, or plus"
    )
    summary: str = Field(
        description="2–3 sentence summary of what this company is looking for in the ideal candidate"
    )


class RewrittenPoint(BaseModel):
    """Response model for the L2 Point Rewriter.

    The rewriter takes an approved L1 point and a JD analysis,
    then produces a JD-aligned version while preserving metrics
    and core accomplishment.
    """

    refined: CVPointCandidate = Field(description="The JD-rewritten CV point")
    what_changed: str = Field(
        description="Specifically what was modified to align with the JD"
    )
    jd_alignment_score: int = Field(
        ge=0,
        le=10,
        description="How well the rewritten point matches the JD (0=irrelevant, 10=perfect fit)",
    )
    keywords_injected: List[str] = Field(
        description="JD keywords or phrases that were woven into the rewritten bullet"
    )
    metrics_preserved: bool = Field(
        description="True if all original metrics were preserved in the rewrite"
    )


class PointSelection(BaseModel):
    """Response model for the L2 Selector.

    The selector reviews all rewritten candidates and decides which
    ones to include in the final resume, avoiding redundancy.
    """

    selected_ids: List[str] = Field(
        description="IDs of the rewritten points to include in the final resume, ordered by importance"
    )
    rejection_reasons: dict[str, str] = Field(
        default_factory=dict,
        description="Map of rejected point_id → one-line reason for exclusion",
    )
    coverage_score: int = Field(
        ge=0,
        le=10,
        description="How well the selected set covers the JD requirements (0=poor, 10=excellent)",
    )


# ─── Prompt Templates ──────────────────────────────────────────────────


def jd_analysis_prompt(jd_text: str) -> str:
    """Build the JD Analyzer prompt.

    The LLM reads the raw JD text and extracts structured requirements,
    skills, and tone signals for downstream rewriting.
    """
    return f"""You are a senior technical recruiter analyzing a job description.
Your goal is to extract the *true* requirements — not just the listed buzzwords,
but what the hiring manager actually cares about.

## Job Description Text

{jd_text}

## Task
1. Identify the role title.
2. Extract 8–12 key requirements. For each, classify its category and assign
   a priority (5 = must-have, 1 = nice-to-have). Look for language cues:
   - "required", "must have", "essential" → priority 5
   - "preferred", "bonus", "plus", "nice to have" → priority 2–3
   - Unqualified lists → priority 4
3. Capture the company's tone: what kind of person are they looking for?
   (e.g., "fast-paced", "collaborative", "self-starter", "detail-oriented")
4. List must-have vs nice-to-have skills separately.
5. Summarize in 2–3 sentences what the ideal candidate looks like.

Return a JSON object matching the JDAnalysis schema.
"""


def point_rewriter_prompt(
    l1_point: CVPointCandidate,
    jd_analysis: JDAnalysis,
    original_bullet: str,
) -> str:
    """Build the L2 Point Rewriter prompt.

    The LLM receives one approved L1 point and the JD analysis,
    then rewrites the bullet to highlight JD-relevant skills and framing.
    """
    requirements_block = "\n".join(
        f"- [{r.category} | P{r.priority}] {r.text}"
        for r in jd_analysis.key_requirements
    )

    must_have_block = ", ".join(jd_analysis.must_have_skills) or "none"
    nice_block = ", ".join(jd_analysis.nice_to_have_skills) or "none"

    return f"""You are a senior technical resume writer specializing in JD alignment.
You rewrite resume bullets to resonate with specific job descriptions —
without lying, inflating, or inventing metrics.

## Your Rules
1. **Preserve all metrics** from the original point. Do NOT invent new numbers.
2. **Preserve the core accomplishment**. The story must remain true.
3. **Reframe for the JD**: emphasize skills, scope, and outcomes that the JD cares about.
4. **Inject JD keywords naturally**: weave must-have skills into context/result where genuinely applicable.
5. **Match tone**: if the JD says "fast-paced startup", signal speed and ownership.
6. **Max 200 chars** for rendered_bullet. Starts with action_verb. No pronouns.

## JD Analysis

**Role**: {jd_analysis.role_title}
**Tone keywords**: {', '.join(jd_analysis.tone_keywords)}
**Must-have skills**: {must_have_block}
**Nice-to-have skills**: {nice_block}
**Summary**: {jd_analysis.summary}

**Key requirements**:
{requirements_block}

## Original L1 Point (APPROVED — do not degrade quality)

- **rendered_bullet**: {original_bullet}
- **action_verb**: {l1_point.action_verb}
- **context**: {l1_point.context}
- **result**: {l1_point.result}
- **skills**: {', '.join(l1_point.skills_utilized) or 'none'}
- **metrics**: {', '.join(l1_point.impact_metrics) or 'none'}
- **situation**: {l1_point.extended_context_situation}
- **task**: {l1_point.extended_context_task}

## Task
Rewrite the point above to maximize JD alignment while obeying all rules.

Return a JSON object matching the RewrittenPoint schema with:
- refined: the rewritten CVPointCandidate
- what_changed: specifically what was modified
- jd_alignment_score: 0–10 score
- keywords_injected: list of JD terms you naturally included
- metrics_preserved: true if all original metrics survived the rewrite
"""


def selection_prompt(
    rewritten_points: List[RewrittenPoint],
    jd_analysis: JDAnalysis,
    point_id_map: dict[str, str],
) -> str:
    """Build the L2 Selector prompt.

    The LLM reviews all rewritten candidates and decides which subset
    to include, avoiding redundancy and maximizing JD coverage.
    """
    bullets_block = "\n".join(
        f"ID: {point_id_map.get(i, str(i))}\n"
        f"  bullet: {rp.refined.rendered_bullet}\n"
        f"  alignment_score: {rp.jd_alignment_score}\n"
        f"  keywords_injected: {', '.join(rp.keywords_injected)}\n"
        f"  metrics_preserved: {rp.metrics_preserved}\n"
        for i, rp in enumerate(rewritten_points)
    )

    requirements_block = "\n".join(
        f"- [{r.category} | P{r.priority}] {r.text}"
        for r in jd_analysis.key_requirements
    )

    return f"""You are a hiring manager selecting the best resume bullets for a candidate.
You have a pool of rewritten CV points, each aligned to the JD.
Your job is to pick the **strongest, least redundant subset** that covers
the JD's must-have requirements.

## JD Requirements
{requirements_block}

## Rewritten Candidates
{bullets_block}

## Selection Rules
1. **No redundancy**: if two points say the same thing, pick the stronger one.
2. **Prioritize must-haves**: bullets that hit P5 requirements are gold.
3. **Preserve metrics**: prefer bullets where metrics_preserved is true.
4. **Balance breadth**: don't pick 5 backend points if the JD also wants frontend.
5. **Max 8 points** for a single job entry (this is a per-experience selection).

## Task
Return a JSON object matching the PointSelection schema with:
- selected_ids: ordered list of IDs to include (best first)
- rejection_reasons: map of excluded ID → one-line reason
- coverage_score: 0–10 assessment of how well the selected set covers the JD
"""
