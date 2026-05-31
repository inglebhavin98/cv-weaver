"""Parse knowledge base markdown files into structured Story objects.

Each experience / project file is a Story Portfolio:
- YAML frontmatter (file_id, company, position, date, etc.)
- Optional context paragraph (enriches all stories)
- ## Story sections with narrative + metadata hints

Metadata hints are parsed from the end of each story:
  _Skills_: Python, Redis
  _Metrics_: P95 latency 800ms → 120ms
  _Team_: 3 engineers, 6 weeks
  _Role_: Senior Software Engineer
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# ─── Data Models ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class Story:
    """A single narrative chunk under a `##` heading."""

    title: str
    body: str
    skills: List[str]
    metrics: List[str]
    team: Optional[str]
    role: Optional[str]
    raw_text: str  # Full text including metadata hints, for source traceability


@dataclass(frozen=True)
class ExperienceFile:
    """Parsed representation of one experience / project markdown file."""

    file_id: str
    frontmatter: Dict[str, Any]
    context_paragraph: Optional[str]
    stories: List[Story]
    source_type: str  # "experience" or "project"


# ─── Regex Patterns ────────────────────────────────────────────────────

# Metadata hint lines at the end of a story block
_HINT_RE = re.compile(
    r"^_(Skills|Metrics|Team|Role)_\s*:\s*(.+)$",
    re.MULTILINE | re.IGNORECASE,
)

# Frontmatter delimiters
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)^---\s*\n", re.DOTALL | re.MULTILINE)


# ─── Public API ────────────────────────────────────────────────────────


def parse_file(file_path: Path, source_type: str) -> ExperienceFile:
    """Parse a knowledge base markdown file into an ExperienceFile.

    Args:
        file_path: Path to the `.md` file.
        source_type: "experience" or "project".

    Returns:
        An ExperienceFile with frontmatter, context, and parsed stories.

    Raises:
        ValueError: If frontmatter is missing or malformed.
    """
    text = file_path.read_text(encoding="utf-8")

    # 1. Extract YAML frontmatter
    frontmatter_match = _FRONTMATTER_RE.match(text)
    if not frontmatter_match:
        raise ValueError(f"Missing YAML frontmatter in {file_path}")

    frontmatter_raw = frontmatter_match.group(1)
    frontmatter = yaml.safe_load(frontmatter_raw) or {}
    file_id = frontmatter.get("file_id")
    if not file_id:
        raise ValueError(f"Missing 'file_id' in frontmatter of {file_path}")

    # 2. Strip frontmatter to get body text
    body_start = frontmatter_match.end()
    body_text = text[body_start:].strip()

    # 3. Split body into context paragraph and stories
    stories, context_paragraph = _split_stories(body_text)

    return ExperienceFile(
        file_id=file_id,
        frontmatter=frontmatter,
        context_paragraph=context_paragraph,
        stories=stories,
        source_type=source_type,
    )


# ─── Internal Helpers ─────────────────────────────────────────────────


def _split_stories(body_text: str) -> tuple[List[Story], Optional[str]]:
    """Split body text into an optional context paragraph and a list of Stories.

    Stories are blocks starting with `## ` headings. Any text before the first
    `## ` is treated as the context paragraph.
    """
    # Split on `## ` but keep the headings as part of each chunk
    # Use a positive lookahead so the delimiter stays with the story
    parts = re.split(r"(?=^## )", body_text, flags=re.MULTILINE)

    # Filter out empty strings
    parts = [p.strip() for p in parts if p.strip()]

    if not parts:
        return [], None

    context_paragraph: Optional[str] = None
    story_parts = parts

    # If the first part doesn't start with ##, it's the context paragraph
    if not parts[0].startswith("##"):
        context_paragraph = parts[0]
        story_parts = parts[1:]

    stories = [_parse_story(p) for p in story_parts]
    return stories, context_paragraph


def _parse_story(story_text: str) -> Story:
    """Parse a single story block (starting with `## Title`) into a Story."""
    lines = story_text.splitlines()

    # First line is the heading: "## Payment Orchestration Overhaul"
    title_line = lines[0].lstrip("#").strip()
    remaining_lines = lines[1:]

    # Find metadata hint lines at the end
    skills: List[str] = []
    metrics: List[str] = []
    team: Optional[str] = None
    role: Optional[str] = None

    # Walk backwards from the end to find contiguous hint lines
    hint_end_idx = len(remaining_lines)
    for i in range(len(remaining_lines) - 1, -1, -1):
        line = remaining_lines[i].strip()
        if not line:
            continue
        match = _HINT_RE.match(line)
        if match:
            key = match.group(1).lower()
            value = match.group(2).strip()
            if key == "skills":
                skills = [s.strip() for s in value.split(",")]
            elif key == "metrics":
                metrics = [m.strip() for m in value.split(",")]
            elif key == "team":
                team = value
            elif key == "role":
                role = value
            hint_end_idx = i
        else:
            break  # Stop at first non-hint line when walking backwards

    # Body is everything between the heading and the hints
    # But we need to be careful: hints might not be at the very end if there are blank lines
    # Actually, we track hint_end_idx as the index of the first hint line from the top
    # Wait, I walked backwards. The first hint encountered from bottom is at index i.
    # The hints are contiguous at the end. So body is lines[1:hint_end_idx]
    # But we need to handle the case where hint_end_idx is the index of the LAST hint line, not first.
    # Let me reconsider.

    # Actually, let me re-approach: collect all hint lines from the end, contiguously.
    hint_lines: List[tuple[int, str, str]] = []  # (index, key, value)
    for i in range(len(remaining_lines) - 1, -1, -1):
        line = remaining_lines[i].strip()
        if not line:
            continue
        match = _HINT_RE.match(line)
        if match:
            hint_lines.append((i, match.group(1).lower(), match.group(2).strip()))
        else:
            break

    # hint_lines are in reverse order (bottom to top)
    if hint_lines:
        first_hint_idx = min(idx for idx, _, _ in hint_lines)
        body_lines = remaining_lines[:first_hint_idx]
    else:
        body_lines = remaining_lines

    body = "\n".join(body_lines).strip()
    raw_text = "\n".join(remaining_lines).strip()

    return Story(
        title=title_line,
        body=body,
        skills=skills,
        metrics=metrics,
        team=team,
        role=role,
        raw_text=raw_text,
    )
