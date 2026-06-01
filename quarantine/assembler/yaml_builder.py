"""Assembler: builds a RenderCV-compatible YAML file from profile + DB content.

The pipeline:
    1. Read profile.yaml (base RenderCV file with personal info + semi-static sections).
    2. Query the DB for approved CV points grouped by source experience/project.
    3. Query knowledge_sources for per-experience metadata (company, position, date, summary).
    4. Build dynamic sections (experience, projects, skills) and merge into cv.sections.
    5. Write the complete YAML to disk.
    6. (Optional) Call rendercv_integration.render_pdf to produce the PDF.

Why build as a dict and use yaml.safe_dump?
- PyYAML handles escaping, indentation, and multiline strings correctly.
- The resulting YAML is human-readable and debuggable.
- We can inspect the dict before writing for testing.
"""

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from cv_weaver.models.schemas import CVPoint


def read_profile_yaml(profile_path: Path) -> dict[str, Any]:
    """Read the base profile.yaml into a Python dict.

    Args:
        profile_path: Path to profile.yaml.

    Returns:
        The parsed YAML content as a dict.
    """
    content = profile_path.read_text(encoding="utf-8")
    return yaml.safe_load(content) or {}


def build_experience_section(
    source_metadata: dict[str, Any],
    points: List[CVPoint],
) -> dict[str, Any]:
    """Build a single RenderCV experience entry from source metadata + approved points.

    Args:
        source_metadata: Dict with keys: company, position, date, start_date,
            end_date, location, summary.
        points: Approved CVPoints derived from this source.

    Returns:
        A RenderCV ExperienceEntry dict.
    """
    entry: dict[str, Any] = {
        "company": source_metadata.get("company", ""),
        "position": source_metadata.get("position", ""),
        "highlights": [p.rendered_bullet for p in points],
    }

    # Use custom date if provided, otherwise fall back to start_date/end_date
    if source_metadata.get("date"):
        entry["date"] = source_metadata["date"]
    else:
        if source_metadata.get("start_date"):
            entry["start_date"] = source_metadata["start_date"]
        if source_metadata.get("end_date"):
            entry["end_date"] = source_metadata["end_date"]

    if source_metadata.get("location"):
        entry["location"] = source_metadata["location"]
    if source_metadata.get("summary"):
        entry["summary"] = source_metadata["summary"]

    return entry


def build_project_section(
    source_metadata: dict[str, Any],
    points: List[CVPoint],
) -> dict[str, Any]:
    """Build a single RenderCV project entry from source metadata + approved points.

    Args:
        source_metadata: Dict with keys: name (from file_id or position), date,
            start_date, end_date, location, summary.
        points: Approved CVPoints derived from this source.

    Returns:
        A RenderCV NormalEntry dict for projects.
    """
    entry: dict[str, Any] = {
        "name": source_metadata.get("position", source_metadata.get("file_id", "")),
        "highlights": [p.rendered_bullet for p in points],
    }

    if source_metadata.get("date"):
        entry["date"] = source_metadata["date"]
    else:
        if source_metadata.get("start_date"):
            entry["start_date"] = source_metadata["start_date"]
        if source_metadata.get("end_date"):
            entry["end_date"] = source_metadata["end_date"]

    if source_metadata.get("location"):
        entry["location"] = source_metadata["location"]
    if source_metadata.get("summary"):
        entry["summary"] = source_metadata["summary"]

    return entry


def build_skills_section(points: List[CVPoint]) -> List[dict[str, str]]:
    """Aggregate skills from selected points into RenderCV OneLineEntry format.

    Args:
        points: All approved CVPoints selected for the final CV.

    Returns:
        List of {label, details} dicts. For now, groups all skills under a
        single "Skills" label. Future: allow user-defined skill categories.
    """
    all_skills: set[str] = set()
    for p in points:
        all_skills.update(p.metadata.skills_utilized)

    if not all_skills:
        return []

    # TODO: In the future, support user-defined skill categories.
    # For now, dump everything under one label.
    return [
        {
            "label": "Skills",
            "details": ", ".join(sorted(all_skills)),
        }
    ]


def assemble_cv_yaml(
    profile_path: Path,
    experience_sources: List[dict[str, Any]],
    project_sources: List[dict[str, Any]],
    points: List[CVPoint],
    output_path: Path,
) -> Path:
    """Build the complete RenderCV YAML and write it to disk.

    Args:
        profile_path: Path to profile.yaml (base RenderCV file).
        experience_sources: List of knowledge_source metadata dicts for experiences.
        project_sources: List of knowledge_source metadata dicts for projects.
        points: All approved CVPoints selected for the CV.
        output_path: Where to write the assembled YAML.

    Returns:
        Path to the written YAML file.
    """
    # 1. Read base profile
    cv_data = read_profile_yaml(profile_path)

    # Ensure cv.sections exists
    cv_data.setdefault("cv", {})
    cv_data["cv"].setdefault("sections", {})
    sections: dict[str, Any] = cv_data["cv"]["sections"]

    # 2. Group points by source file_id
    points_by_source: dict[str, List[CVPoint]] = defaultdict(list)
    for p in points:
        points_by_source[p.source.file_id].append(p)

    # 3. Build experience entries
    experience_entries: List[dict[str, Any]] = []
    for src in experience_sources:
        file_id = src.get("file_id")
        src_points = points_by_source.get(file_id, [])
        if src_points:
            experience_entries.append(build_experience_section(src, src_points))
    if experience_entries:
        sections["experience"] = experience_entries

    # 4. Build project entries
    project_entries: List[dict[str, Any]] = []
    for src in project_sources:
        file_id = src.get("file_id")
        src_points = points_by_source.get(file_id, [])
        if src_points:
            project_entries.append(build_project_section(src, src_points))
    if project_entries:
        sections["projects"] = project_entries

    # 5. Build skills section
    skills_entries = build_skills_section(points)
    if skills_entries:
        sections["skills"] = skills_entries

    # 6. Write YAML
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            cv_data,
            f,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=1000,  # Avoid line-wrapping bullets
        )

    return output_path
