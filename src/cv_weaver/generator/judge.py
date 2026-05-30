"""LLM-as-Judge module for evaluating CV point quality.

This module is used **only** in benchmark/evaluation contexts.
It is NOT part of the live generator pipeline.

The judge takes a CVPoint and evaluates it across multiple dimensions
(impact, ATS-friendliness, completeness) using a separate LLM call
with a structured scoring rubric.
"""

from cv_weaver.models.schemas import CVPoint, PointScores


def judge_point(point: CVPoint, model: str | None = None) -> PointScores:
    """Evaluate a single CVPoint and return structured scores.

    Args:
        point: The CVPoint to evaluate.
        model: Optional override for the judge model.

    Returns:
        PointScores with impact_score, ats_score, completeness_score.
    """
    raise NotImplementedError("Judge evaluation pipeline not yet implemented.")


def judge_batch(points: list[CVPoint], model: str | None = None) -> list[PointScores]:
    """Evaluate multiple CVPoints in a single batch call.

    Args:
        points: List of CVPoints to evaluate.
        model: Optional override for the judge model.

    Returns:
        List of PointScores in the same order as input.
    """
    raise NotImplementedError("Batch judge evaluation not yet implemented.")
