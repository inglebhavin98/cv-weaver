"""SQLite database initialization and schema management.

Uses raw sqlite3 — no ORM. All DDL is explicit and version-controlled here.
"""

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
-- Canonical CV point storage
CREATE TABLE IF NOT EXISTS cv_points (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source_file_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('experience', 'project', 'education', 'static')),
    raw_dump_excerpt TEXT NOT NULL,
    situation TEXT NOT NULL,
    task TEXT NOT NULL,
    action_verb TEXT NOT NULL,
    context TEXT NOT NULL,
    result TEXT NOT NULL,
    rendered_bullet TEXT NOT NULL,
    impact_metrics TEXT NOT NULL DEFAULT '[]',
    skills_utilized TEXT NOT NULL DEFAULT '[]',
    classification_type TEXT CHECK (classification_type IN ('general', 'domain-specific', 'jd-specific')),
    domain_tags TEXT NOT NULL DEFAULT '[]',
    target_jd_id TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'archived')),
    parent_point_id TEXT,
    impact_score INTEGER CHECK (impact_score >= 0 AND impact_score <= 10),
    ats_score INTEGER CHECK (ats_score >= 0 AND ats_score <= 10),
    completeness_score INTEGER CHECK (completeness_score >= 0 AND completeness_score <= 10),
    embedding BLOB,

    FOREIGN KEY (source_file_id) REFERENCES knowledge_sources(file_id),
    FOREIGN KEY (parent_point_id) REFERENCES cv_points(id)
);

-- Indexes for cv_points
CREATE INDEX IF NOT EXISTS idx_cv_points_status ON cv_points(status);
CREATE INDEX IF NOT EXISTS idx_cv_points_source ON cv_points(source_file_id);
CREATE INDEX IF NOT EXISTS idx_cv_points_parent ON cv_points(parent_point_id);
CREATE INDEX IF NOT EXISTS idx_cv_points_classification ON cv_points(classification_type);

-- Knowledge base source files (experience, project, etc.)
CREATE TABLE IF NOT EXISTS knowledge_sources (
    file_id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('experience', 'project', 'education', 'static')),
    company TEXT,
    position TEXT,
    roles TEXT,  -- JSON array of {title, start_date, end_date} for promotions
    date TEXT,
    start_date TEXT,
    end_date TEXT,
    location TEXT,
    summary TEXT,
    employment_type TEXT,
    team_size INTEGER,
    reporting_to TEXT,
    domain_tags TEXT NOT NULL DEFAULT '[]',
    last_scanned TEXT NOT NULL
);

-- Redundancy detection flags
CREATE TABLE IF NOT EXISTS redundancy_pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    point_a_id TEXT NOT NULL,
    point_b_id TEXT NOT NULL,
    similarity_score REAL NOT NULL,
    flagged_at TEXT NOT NULL,
    resolution TEXT NOT NULL DEFAULT 'pending' CHECK (resolution IN ('pending', 'kept', 'discarded', 'merged')),
    resolved_at TEXT,

    UNIQUE (point_a_id, point_b_id),
    FOREIGN KEY (point_a_id) REFERENCES cv_points(id),
    FOREIGN KEY (point_b_id) REFERENCES cv_points(id)
);

-- Job descriptions for JD-based customization
CREATE TABLE IF NOT EXISTS job_descriptions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT,
    raw_text TEXT NOT NULL,
    domain_tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
"""


def init_db(db_path: str | Path) -> None:
    """Initialize the SQLite database with the full schema.

    Args:
        db_path: Path to the SQLite database file. Parent directory is created if needed.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Return a sqlite3 connection with row factory enabled.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        An open sqlite3.Connection.
    """
    conn = sqlite3.connect(Path(db_path))
    conn.row_factory = sqlite3.Row
    return conn
