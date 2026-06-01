"""Validation rules for CV points and assembled CVs.

All rules are pure functions that accept a CVPoint (or list of CVPoints) and return
a RuleResult. This separation keeps rules testable, version-controllable, and
independent of orchestration logic.

Why separate rules from orchestration?
- You can unit-test each rule in isolation.
- You can A/B test rule combinations in benchmarks.
- You can see exactly what constraints exist by reading one file.
"""

from dataclasses import dataclass
from typing import List, Optional

from cv_weaver.models.schemas import CVPoint

# ─── RuleResult dataclass ──────────────────────────────────────────────

@dataclass(frozen=True)
class RuleResult:
    """Outcome of a single validation rule.

    Attributes:
        name: Machine-readable rule identifier.
        passed: Whether the rule passed.
        message: Human-readable explanation.
        suggestion: Guidance for fixing the violation.
        is_blocking: If False, the user may decline the suggestion and proceed.
            Blocking rules (pronouns, length, verb-start) MUST be fixed.
            Non-blocking rules (metric suggestion) trigger a question but are optional.
    """

    name: str
    passed: bool
    message: str
    suggestion: Optional[str] = None
    is_blocking: bool = True


# ─── Point-Level Rules ─────────────────────────────────────────────────
# These run against a single CVPoint during the generation pipeline.


PRONOUNS = {"i", "me", "my", "we", "our", "us", "myself", "ourselves"}


def starts_with_action_verb(point: CVPoint) -> RuleResult:
    """ rendered_bullet must begin with the action_verb. """
    bullet = point.rendered_bullet.strip()
    verb = point.components.action_verb.strip()
    passed = bullet.lower().startswith(verb.lower())
    return RuleResult(
        name="starts_with_action_verb",
        passed=passed,
        message="Bullet starts with action verb." if passed else f"Bullet must start with '{verb}'.",
        suggestion=None if passed else f"Rephrase so the bullet begins with '{verb}'.",
    )


def under_200_chars(point: CVPoint) -> RuleResult:
    """ rendered_bullet must be at most 200 characters. """
    length = len(point.rendered_bullet)
    passed = length <= 200
    return RuleResult(
        name="under_200_chars",
        passed=passed,
        message=f"Bullet is {length} characters." if passed else f"Bullet is {length} characters (max 200).",
        suggestion=None if passed else "Trim scope or split into two bullets.",
    )


def no_pronouns(point: CVPoint) -> RuleResult:
    """ rendered_bullet must not contain first-person pronouns. """
    words = point.rendered_bullet.lower().split()
    found = [w for w in words if w.strip(".,;:!?") in PRONOUNS]
    passed = not found
    return RuleResult(
        name="no_pronouns",
        passed=passed,
        message="No pronouns found." if passed else f"Found pronouns: {', '.join(found)}.",
        suggestion=None if passed else "Remove pronouns — bullets should be agentless (e.g., 'Led team' not 'I led the team').",
    )


def has_metrics_or_flagged(point: CVPoint) -> RuleResult:
    """Bullet must contain quantifiable metrics. Blocking — saves an LLM prober call."""
    passed = point.has_metrics
    return RuleResult(
        name="has_metrics_or_flagged",
        passed=passed,
        message="Bullet contains metrics." if passed else "Bullet has no quantifiable metrics.",
        suggestion=None if passed else "Can you quantify the result? (e.g., saved 10 hours/week, increased efficiency by 15%, reduced latency by 60%)",
        is_blocking=True,
    )


WEAK_VERBS = {
    "helped",
    "assisted",
    "participated",
    "worked",
    "was",
    "were",
    "involved",
    "contributed",
    "supported",
    "handled",
    "did",
    "responsible",
}


def strong_action_verb(point: CVPoint) -> RuleResult:
    """action_verb must be high-impact, not weak or passive. Blocking."""
    verb = point.components.action_verb.lower().strip()
    passed = verb not in WEAK_VERBS
    return RuleResult(
        name="strong_action_verb",
        passed=passed,
        message=f"Verb '{verb}' is strong." if passed else f"Verb '{verb}' is weak or passive.",
        suggestion=None if passed else f"The verb '{verb}' is passive. Did you 'Architect', 'Manage', 'Develop', or 'Lead' this instead?",
        is_blocking=True,
    )


# Ordered list of point-level BLOCKING rules.
# Structural validator enforces hard constraints (format, grammar, metrics, verb strength).
# The Semantic Prober LLM handles deeper semantic gaps (scope, business linkage, etc.).
POINT_LEVEL_RULES: List = [
    starts_with_action_verb,
    under_200_chars,
    no_pronouns,
    has_metrics_or_flagged,
    strong_action_verb,
]


# ─── Whole-CV Rules ──────────────────────────────────────────────────────
# These run against the full set of selected CVPoints before YAML assembly.


def no_duplicate_verbs(points: List[CVPoint]) -> RuleResult:
    """ Avoid repeating the same action verb across multiple bullets. """
    verbs: dict[str, int] = {}
    for p in points:
        v = p.components.action_verb.lower()
        verbs[v] = verbs.get(v, 0) + 1

    duplicates = {v: c for v, c in verbs.items() if c > 1}
    passed = not duplicates
    return RuleResult(
        name="no_duplicate_verbs",
        passed=passed,
        message="All verbs are unique." if passed else f"Duplicate verbs: {duplicates}.",
        suggestion=None if passed else "Replace duplicate verbs with synonyms (e.g., 'Led' → 'Directed', 'Spearheaded').",
    )


def skill_coverage_minimum(points: List[CVPoint], minimum_skills: int = 5) -> RuleResult:
    """ Ensure the selected points cover at least N unique skills. """
    all_skills = set()
    for p in points:
        all_skills.update(p.metadata.skills_utilized)
    passed = len(all_skills) >= minimum_skills
    return RuleResult(
        name="skill_coverage_minimum",
        passed=passed,
        message=f"Covers {len(all_skills)} unique skills." if passed else f"Only {len(all_skills)} unique skills covered (min {minimum_skills}).",
        suggestion=None if passed else "Select points that showcase different technologies or methodologies.",
    )


def consistent_past_tense(points: List[CVPoint]) -> RuleResult:
    """ Heuristic: all action verbs should be past tense. """
    # This is a placeholder. A real implementation would use a POS tagger or
    # a curated list of past-tense verbs. For now, we flag if any verb ends
    # in common present-tense patterns.
    present_markers = ["ing", "s", "es"]
    flagged = []
    for p in points:
        verb = p.components.action_verb.lower()
        # Simple heuristic: verbs ending in 'ing' or bare present forms
        if verb.endswith("ing"):
            flagged.append(verb)

    passed = not flagged
    return RuleResult(
        name="consistent_past_tense",
        passed=passed,
        message="All verbs appear to be past tense." if passed else f"Possible present-tense verbs: {flagged}.",
        suggestion=None if passed else "Use past-tense verbs (e.g., 'Led' not 'Leading', 'Built' not 'Building').",
    )


# Ordered list of all whole-CV rules. The validator runs these in order.
WHOLE_CV_RULES: List = [
    no_duplicate_verbs,
    skill_coverage_minimum,
    consistent_past_tense,
]
