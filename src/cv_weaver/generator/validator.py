"""Validation orchestrator for CV points and assembled CVs.

This module imports rule definitions from `validation_rules.py` and exposes
high-level `validate_point` and `validate_cv` functions. It does not contain
rule logic itself — that lives in `validation_rules.py` so rules can be tested
and versioned independently.

Why two layers?
- Point-level: fast feedback during generation. Catches individual bullet quality.
- Whole-CV: cross-bullet quality check before YAML export. Casts verb diversity,
  skill coverage, and tone consistency.
"""

from dataclasses import dataclass
from typing import List, Optional

from cv_weaver.models.schemas import CVPoint

from .validation_rules import (
    POINT_LEVEL_RULES,
    WHOLE_CV_RULES,
    RuleResult,
)


# ─── ValidationResult dataclass ────────────────────────────────────────

@dataclass(frozen=True)
class ValidationResult:
    """Aggregated result of running one or more validation rules."""

    passed: bool
    violations: List[RuleResult]
    suggested_fix: Optional[str] = None

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


# ─── Point-Level Validation ────────────────────────────────────────────


def validate_point(point: CVPoint) -> ValidationResult:
    """Run all point-level validation rules against a single CVPoint.

    Args:
        point: The CVPoint to validate.

    Returns:
        A ValidationResult with all failing rules in `violations`.
    """
    violations: List[RuleResult] = []
    suggestions: List[str] = []

    for rule in POINT_LEVEL_RULES:
        result = rule(point)
        if not result.passed:
            violations.append(result)
            if result.suggestion:
                suggestions.append(f"[{result.name}] {result.suggestion}")

    suggested_fix = "\n".join(suggestions) if suggestions else None
    return ValidationResult(
        passed=not violations,
        violations=violations,
        suggested_fix=suggested_fix,
    )


# ─── Whole-CV Validation ───────────────────────────────────────────────


def validate_cv(points: List[CVPoint]) -> ValidationResult:
    """Run all whole-CV validation rules against the selected points.

    Args:
        points: The list of CVPoints selected for final assembly.

    Returns:
        A ValidationResult with all failing rules in `violations`.
    """
    violations: List[RuleResult] = []
    suggestions: List[str] = []

    for rule in WHOLE_CV_RULES:
        result = rule(points)
        if not result.passed:
            violations.append(result)
            if result.suggestion:
                suggestions.append(f"[{result.name}] {result.suggestion}")

    suggested_fix = "\n".join(suggestions) if suggestions else None
    return ValidationResult(
        passed=not violations,
        violations=violations,
        suggested_fix=suggested_fix,
    )
