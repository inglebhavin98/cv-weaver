"""Prompt templates and response models for the Generator Engine.

Three LLM roles:
1. Drafter    — story narrative → CVPointCandidate(s)
2. Refiner    — previous point + user answer → refined CVPointCandidate
3. Judge      — finalized point + rubric → PointScores with reasoning

All prompts are returned as plain strings. The caller injects them into
LLMClient.chat_completion along with the appropriate response_model.
"""

from pathlib import Path
from typing import List

from pydantic import BaseModel, Field

# ─── Unified L1 System Prompt (Version 1, XML-style) ───────────────────
# Loaded raw from external XML file and sent directly to the LLM as-is.
# Modern LLMs (e.g., kimi-k2.6, GPT-4) parse XML natively.
# Sent as `role: "system"` on every LLM call (Drafter, Refiner, Judge).

_SYSTEM_PROMPT_PATH = Path(__file__).with_name("system_prompt_v1.xml")
SYSTEM_PROMPT: str = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()

_PROBER_SYSTEM_PROMPT_PATH = Path(__file__).with_name("system_prompt_prober.xml")
PROBER_SYSTEM_PROMPT: str = _PROBER_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()

_JUDGE_SYSTEM_PROMPT_PATH = Path(__file__).with_name("system_prompt_judge.xml")
JUDGE_SYSTEM_PROMPT: str = _JUDGE_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()


# ─── Response Models for LLM Output ────────────────────────────────────

class CVPointCandidate(BaseModel):
    """Fields the LLM must produce for a new CV point.

    System fields (id, timestamps, source, classification.status,
    generation_level, scores) are injected by the engine after the LLM call.
    """

    extended_context_situation: str = Field(
        description="What was the business or technical problem?"
    )
    extended_context_task: str = Field(
        description="What was your specific responsibility?"
    )
    action_verb: str = Field(
        description="Single past-tense high-impact verb. Must start rendered_bullet."
    )
    context: str = Field(
        description="Scope, problem, or technology stack handled"
    )
    result: str = Field(
        description="Quantifiable business outcome or technical improvement"
    )
    rendered_bullet: str = Field(
        description="Final one-liner starting with action_verb. Max 200 chars. No pronouns (I, me, my, we, our)."
    )
    impact_metrics: List[str] = Field(
        default_factory=list,
        description="Specific numbers, percentages, or time measurements mentioned or implied",
    )
    skills_utilized: List[str] = Field(
        default_factory=list,
        description="Tools, technologies, methodologies used in this story",
    )
    domain_tags: List[str] = Field(
        default_factory=list,
        description="Domain labels for this point, e.g., 'backend', 'fintech'",
    )
    scope_summary: str = Field(
        default="",
        description="1-sentence description of the SPECIFIC accomplishment this candidate covers. Used to scope prober audits so it does not demand coverage of unrelated accomplishments from the same raw story.",
    )


class StoryExtraction(BaseModel):
    """Response model for the L1 Drafter."""

    candidates: List[CVPointCandidate] = Field(
        description="1 to 3 distinct CVPoint candidates extracted from the story"
    )
    reasoning: str = Field(
        description="Brief explanation of why each candidate was chosen and how it maps to the story"
    )


class RefinedPoint(BaseModel):
    """Response model for the L1 Refiner."""

    refined: CVPointCandidate = Field(description="The regenerated CV point")
    what_changed: str = Field(
        description="Specifically what was modified compared to the previous version"
    )


class DimensionScore(BaseModel):
    """One dimension of the L1 Judge rubric."""

    dimension: str
    score: int = Field(ge=0, le=3, description="Score for this dimension")
    reasoning: str = Field(description="Why this score was given")


class PointEvaluation(BaseModel):
    """Response model for the L1 Judge."""

    dimension_scores: List[DimensionScore] = Field(
        description="Score breakdown per rubric dimension"
    )
    impact_score: int = Field(ge=0, le=10)
    ats_score: int = Field(ge=0, le=10)
    completeness_score: int = Field(ge=0, le=10)
    overall_reasoning: str = Field(
        description="Summary of the bullet's strengths and weaknesses"
    )
    specific_suggestions: List[str] = Field(
        default_factory=list,
        description="Concrete improvements the user could make",
    )


class SemanticProberResult(BaseModel):
    """Response model for the L1 Semantic Prober.

    The prober compares a draft CVPoint against the raw narrative story
    to identify semantic gaps: metrics, tech stack, scope, business impact,
    strategic intent, organizational context, leadership scope, cross-functional
    alignment, logic/reality, jargon/obscurity, and recognition scale that the
    draft omitted or diluted.
    """

    has_semantic_gap: bool = Field(
        description="True if the draft omits or dilutes meaningful data present in or strongly implied by the raw story"
    )
    gap_categories: List[str] = Field(
        default_factory=list,
        description="Categories of gaps found: metrics, tech_stack, scope, business, strategic_intent, org_scale, leadership_scope, cross_functional, logic_check, jargon_obscurity, recognition_scale"
    )
    target_question: str = Field(
        description="A single, hyper-targeted CLI question to ask the user. Must be answerable in one sentence. Empty string if no gap."
    )
    what_is_missing: str = Field(
        description="Detailed description of the gap for the Refiner. Empty string if no gap."
    )
    confidence: int = Field(
        ge=0, le=10, description="How certain the prober is that this gap is real (0=guessing, 10=certain)"
    )


# ─── Prompt Templates ──────────────────────────────────────────────────


def drafter_prompt(
    story_title: str,
    story_body: str,
    story_skills: List[str],
    story_metrics: List[str],
    story_team: str | None,
    story_role: str | None,
    context_paragraph: str | None,
) -> str:
    """Build the L1 Drafter prompt.

    The LLM receives the full story narrative + metadata hints + context paragraph
    and returns 1–3 CVPointCandidate objects via structured output.
    """
    skills_hint = f"\n_Skills hint_: {', '.join(story_skills)}" if story_skills else ""
    metrics_hint = f"\n_Metrics hint_: {', '.join(story_metrics)}" if story_metrics else ""
    team_hint = f"\n_Team hint_: {story_team}" if story_team else ""
    role_hint = f"\n_Role hint_: {story_role}" if story_role else ""
    context_block = (
        f"\n## Overall Role Context\n{context_paragraph}\n"
        if context_paragraph
        else ""
    )

    return f"""You are a senior technical resume writer with 15 years of experience.
Your job is to read a narrative story from a candidate's work history and extract
high-impact, STAR-format resume bullet points.

## Task
Read the story below. Extract **1 to 3 distinct CVPoint candidates**.
Each candidate must represent a **separate, concrete accomplishment** from the story.
Do not create redundant points. If the story only has one strong accomplishment, return one.

**CRITICAL — scope isolation:** Each candidate must cover a SEPARATE, concrete accomplishment. For each candidate, write a `scope_summary` field that describes exactly what that candidate covers (e.g., "core identity and onboarding frontend architecture" or "centralized UI design system using Storybook.js"). The prober will use this to avoid demanding that every candidate contain every detail from the full story.

## Rubric for Each Candidate — ALL of these fields are MANDATORY

1. **extended_context_situation**
   - What was the business or technical problem? (1–2 sentences)
   - Example: "Monolithic payments system degraded under 10x traffic spikes during flash sales."

2. **extended_context_task**
   - What was YOUR specific responsibility? (1 sentence)
   - Example: "Lead backend engineer tasked with redesigning the payment flow."

3. **action_verb**
   - Must be a single, past-tense, high-impact verb.
   - Preferred: Led, Architected, Designed, Built, Engineered, Optimized, Delivered,
     Spearheaded, Implemented, Automated, Reduced, Improved, Scaled.
   - New categories to consider: Synthesized, Diagnosed, Evaluated, Extracted,
     Systematized, Streamlined, Centralized, Negotiated, Persuaded, Arbitrated, Facilitated.
   - Avoid: Helped, Assisted, Worked on, Participated in, Was responsible for.

4. **context**
   - What system, team size, or technology scope was involved?
   - Example good: "for a 3-engineer team serving 2M daily users"
   - Example bad: "on the backend"

5. **result**
   - Must be quantifiable or strongly implied.
   - Best: "reducing P95 latency from 800ms to 120ms"
   - Acceptable: "eliminating the primary source of production incidents"
   - Weak: "making things faster"

6. **rendered_bullet**
   - One sentence. Max 200 characters.
   - Starts with the action_verb.
   - No pronouns: I, me, my, we, our.
   - No filler words: "successfully", "effectively", "various".
   - Soft-skill translation: If the story mentions soft skills (communication, teamwork, leadership),
     do NOT write "strong communicator" or "team player". Translate the skill into the specific
     action that proved it (e.g., "Aligned 4 cross-functional teams to resolve blockers").

7. **impact_metrics** (JSON array of strings, e.g., `["latency ↓ 60%"]`)
   - Extract or infer specific numbers from the story.
   - If none exist, return an empty array `[]`. Do NOT hallucinate metrics.

8. **skills_utilized** (JSON array of strings, e.g., `["Python", "Redis"]`)
   - List technologies, languages, frameworks, tools explicitly mentioned.
   - If none, return an empty array `[]`.

9. **domain_tags** (JSON array of strings, e.g., `["backend", "fintech"]`)
   - 1–3 domain labels for this point.
   - If none fit, return an empty array `[]`.

## Output Format
Return a JSON object with EXACTLY this shape. Every field is required.

```json
{{
  "candidates": [
    {{
      "extended_context_situation": "string",
      "extended_context_task": "string",
      "action_verb": "string",
      "context": "string",
      "result": "string",
      "rendered_bullet": "string (max 200 chars, starts with action_verb)",
      "impact_metrics": ["string"],
      "skills_utilized": ["string"],
      "domain_tags": ["string"],
      "scope_summary": "string (1 sentence describing the specific accomplishment this candidate covers)"
    }}
  ],
  "reasoning": "string"
}}
```

## Input Story

### {story_title}
{story_body}{skills_hint}{metrics_hint}{team_hint}{role_hint}{context_block}
"""


_ENGINEERING_SCALE_FALLBACK = """If the user still cannot provide exact business metrics, guide them to quantify ENVIRONMENT SCALE instead:
- Codebase/Data Scale: cluster size, data volume processed, lines of code refactored, number of services.
- Organizational Scope: repositories managed, deployment frequency, engineering org size impacted.
- Technical Complexity: APIs integrated, frameworks used, concurrency or load handled.
Pick the single most impressive and verifiable scale signal."""


def refiner_prompt(
    previous_candidate: CVPointCandidate,
    flaw_description: str,
    user_answer: str,
    context_paragraph: str | None = None,
    prior_clarifications: List[str] | None = None,
) -> str:
    """Build the L1 Refiner prompt.

    The LLM receives the previous draft, the validation flaw that was found,
    the user's answer, and any prior clarifications from earlier rounds.
    It regenerates an improved CVPointCandidate.

    When no metrics exist, a fallback hint is injected to guide the LLM toward
    engineering-scale dimensions rather than forcing hallucinated business outcomes.
    """
    context_block = (
        f"\n## Overall Role Context\n{context_paragraph}\n"
        if context_paragraph
        else ""
    )

    # Cap history to last 2 rounds to prevent prompt bloat and LLM confusion
    capped_clarifications = (prior_clarifications or [])[-2:]
    history_block = ""
    if capped_clarifications:
        history_block = (
            "## Previous Clarifications (last 2 rounds)\n"
            + "\n".join(f"- {c}" for c in capped_clarifications)
            + "\n"
        )

    # Inject engineering-scale fallback when metrics are missing and the flaw is metric-related
    metrics_fallback = ""
    if (
        not previous_candidate.impact_metrics
        and "metric" in flaw_description.lower()
    ):
        metrics_fallback = f"\n## Engineering Scale Fallback\n{_ENGINEERING_SCALE_FALLBACK}\n"

    return f"""You are a senior technical resume writer refining a CV bullet point.

## Previous Draft

- **rendered_bullet**: {previous_candidate.rendered_bullet}
- **situation**: {previous_candidate.extended_context_situation}
- **task**: {previous_candidate.extended_context_task}
- **action_verb**: {previous_candidate.action_verb}
- **context**: {previous_candidate.context}
- **result**: {previous_candidate.result}
- **skills**: {', '.join(previous_candidate.skills_utilized) or 'none'}
- **metrics**: {', '.join(previous_candidate.impact_metrics) or 'none'}

## Issue to Fix
{flaw_description}{metrics_fallback}

## User's Input
"{user_answer}"

{history_block}## Task
Regenerate the CV point incorporating the user's input.
You may modify any field. Preserve what was already strong. Fix only the issue.
Do NOT drop data from previous clarifications — retain every improvement made so far.
Do NOT merge accomplishments from other candidates into this bullet. Only refine the CURRENT bullet's scope. If the user's answer mentions work from a different candidate, ignore it and focus on improving this bullet only.

## Output Format
Return **ONLY** a JSON object with this EXACT top-level shape. Do NOT return a list. Do NOT return the fields flat.

```json
{{
  "refined": {{
    "extended_context_situation": "string",
    "extended_context_task": "string",
    "action_verb": "string",
    "context": "string",
    "result": "string",
    "rendered_bullet": "string (max 200 chars, starts with action_verb)",
    "impact_metrics": ["string"],
    "skills_utilized": ["string"],
    "domain_tags": ["string"]
  }},
  "what_changed": "string"
}}
```

**CRITICAL:** The top-level keys MUST be `"refined"` and `"what_changed"`. The candidate data lives INSIDE `"refined"`.{context_block}
"""


def judge_prompt(
    candidate: CVPointCandidate,
    story_title: str,
    source_type: str = "experience",
) -> str:
    """Build the L1 Judge prompt.

    The LLM receives a finalized CVPointCandidate (after QnA convergence)
    and evaluates it against a rubric. It is blind to authorship.

    Args:
        source_type: "experience" or "project". When "project", Dimension 4
            evaluates "Technical Complexity & Adoption" instead of "Business Outcome".
    """
    if source_type == "project":
        d4_rubric = """### Dimension 4: Technical Complexity & Adoption (0–2)
- 2 = Demonstrates significant technical depth AND evidence of adoption/wins (e.g., hackathon placement, active users/downloads, grant funding, complex framework integration, lines of code refactored)
- 1 = Technical work described but no evidence of complexity or adoption (e.g., "built a React app" with no scale or outcome)
- 0 = No technical outcome or adoption signal stated"""
        d4_name = "Technical Complexity & Adoption"
    else:
        d4_rubric = """### Dimension 4: Business Outcome (0–2)
- 2 = Clear link to revenue, cost, risk reduction, or user experience
- 1 = Technical outcome stated but business link missing
- 0 = No outcome stated (only describes what was done)"""
        d4_name = "Business Outcome"

    return f"""You are an independent resume reviewer. You did NOT write this bullet.
You are evaluating a CV bullet point as if reviewing a portfolio from a stranger.
Be critical. A 10/10 is rare.

## Bullet to Evaluate

**Title**: {story_title}
**Source Type**: {source_type}

**rendered_bullet**: {candidate.rendered_bullet}
**action_verb**: {candidate.action_verb}
**context**: {candidate.context}
**result**: {candidate.result}
**skills**: {', '.join(candidate.skills_utilized) or 'none listed'}
**metrics**: {', '.join(candidate.impact_metrics) or 'none listed'}

## Rubric — Evaluate Each Dimension

### Dimension 1: Quantification (0–3)
- 3 = Exact metric with before/after comparison ("reduced from X to Y")
- 2 = Metric present but no baseline ("reduced latency to 120ms")
- 1 = Vague quantification ("significantly reduced", "improved performance")
- 0 = No numbers, percentages, or time measurements at all

### Dimension 2: Action Clarity (0–3)
- 3 = Unambiguous high-impact verb (Architected, Led, Engineered, Automated)
- 2 = Clear but common verb (Built, Implemented, Developed)
- 1 = Weak or passive verb (Assisted with, Participated in, Helped)
- 0 = No clear action or vague phrasing ("Was involved in", "Worked on")

### Dimension 3: Scope Signal (0–2)
- 2 = Clear scale (users affected, systems touched, team size, data volume)
- 1 = Implied scope but not explicit ("production system" without scale)
- 0 = No scope signal at all

{d4_rubric}

### Dimension 5: ATS & Keyword Formatting (0–2)
- 2 = Flawless: skills embedded naturally in prose, acronyms expanded on first use, no pronouns, no keyword stuffing
- 1 = Standard formatting: readable and professional, but acronyms unexpanded or minor keyword density issues
- 0 = Poor: pronouns used (I, me, my, we, our), blatant keyword stuffing, or broken grammar that would trigger ATS rejection

## Scoring Formula
- impact_score = Dimension 1 + Dimension 2 + Dimension 3 + Dimension 4 + Dimension 5 (0–12, then clamped 0–10)
  * Because the raw sum can exceed 10, the impact_score is the raw sum clamped to a maximum of 10.
- ats_score = round((Dimension 2 + Dimension 3 + Dimension 5 + (1 if Dimension 1 ≥ 2 else 0)) × 10 / 8)
  * This weights Action Clarity (Dim 2), Scope Signal (Dim 3), and ATS Formatting (Dim 5) highest,
    with a bonus for strong quantification (Dim 1 ≥ 2). Max numerator = 8. Scaled 0–10.
- completeness_score = sum of all dimensions (0–12, then clamped 0–10)
  * Raw sum of D1–D5, clamped to a maximum of 10.

## Output Format
Return **ONLY** a JSON object with this EXACT shape. Do NOT return a list at the top level.

```json
{{
  "dimension_scores": [
    {{"dimension": "Dimension 1: Quantification", "score": 0, "reasoning": "string"}},
    {{"dimension": "Dimension 2: Action Clarity", "score": 0, "reasoning": "string"}},
    {{"dimension": "Dimension 3: Scope Signal", "score": 0, "reasoning": "string"}},
    {{"dimension": "Dimension 4: {d4_name}", "score": 0, "reasoning": "string"}},
    {{"dimension": "Dimension 5: ATS & Keyword Formatting", "score": 0, "reasoning": "string"}}
  ],
  "impact_score": 0,
  "ats_score": 0,
  "completeness_score": 0,
  "overall_reasoning": "string",
  "specific_suggestions": ["string"]
}}
```

**CRITICAL:** Each `dimension_scores` item MUST have `"dimension"` as a string, `"score"` as an integer 0–3, and `"reasoning"` as a string. The `dimension` field must be the exact dimension name shown above.
"""


def prober_prompt(
    story_title: str,
    story_body: str,
    candidate: CVPointCandidate,
) -> str:
    """Build the L1 Semantic Prober prompt.

    The LLM receives the full raw story + the current draft candidate,
    then identifies semantic gaps where the draft left technical depth,
    metrics, or scale on the table.

    **Scope isolation:** The candidate's ``scope_summary`` tells the prober
    which specific accomplishment to audit. The prober must NOT demand
    coverage of other distinct accomplishments from the same raw story.
    """
    scope_hint = f"""## Candidate Scope
This candidate covers: {candidate.scope_summary or "(unspecified — audit against the full story)"}

**CRITICAL INSTRUCTION:** The raw story may contain MULTIPLE distinct accomplishments. You must ONLY audit gaps WITHIN the candidate's scope above. Do NOT flag that the draft omits other accomplishments from the raw story. For example, if the scope is "UI design system," do NOT complain that the draft omits "identity and onboarding architecture." Those are separate accomplishments.
""" if candidate.scope_summary else ""

    return f"""## Raw Story (Narrative)

### {story_title}
{story_body}

{scope_hint}
## Draft CV Point

- **rendered_bullet**: {candidate.rendered_bullet}
- **action_verb**: {candidate.action_verb}
- **context**: {candidate.context}
- **result**: {candidate.result}
- **skills**: {', '.join(candidate.skills_utilized) or 'none'}
- **metrics**: {', '.join(candidate.impact_metrics) or 'none'}
- **domain_tags**: {', '.join(candidate.domain_tags) or 'none'}

## Task
Compare the DRAFT against the RAW STORY, but ONLY within the candidate's scope above. Identify every piece of technical depth, quantified impact, scale signal, business linkage, strategic intent, jargon/obscurity, or recognition scale that appears in or is strongly implied by the raw story WITHIN THIS SCOPE but is MISSING, DILUTED, or VAGUE in the draft.

## Output Format
Return **ONLY** a JSON object with this EXACT shape:

```json
{{
  "has_semantic_gap": true,
  "gap_categories": ["metrics", "tech_stack", "scope", "business", "strategic_intent", "org_scale", "leadership_scope", "cross_functional", "logic_check", "jargon_obscurity", "recognition_scale"],
  "target_question": "string (one hyper-specific sentence, empty if no gap)",
  "what_is_missing": "string (detailed gap description, empty if no gap)",
  "confidence": 8
}}
```

**CRITICAL:** `confidence` MUST be an integer between 0 and 10 (e.g., 7, 8, 9). Do NOT use fractional values like 7.5 or 8.2.
"""
