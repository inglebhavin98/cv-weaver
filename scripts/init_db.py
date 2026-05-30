#!/usr/bin/env python3
"""One-shot script to initialize the cv-weaver SQLite database."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cv_weaver.storage.db import init_db

if __name__ == "__main__":
    db_path = Path(__file__).parent.parent / "data" / "cv_weaver.db"
    init_db(db_path)
    print(f"Database initialized at: {db_path}")
