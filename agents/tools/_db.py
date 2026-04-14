# agents/tools/_db.py
"""Synchronous SQLite helpers for use inside CrewAI tools.

Tools run in CrewAI's thread pool (not the FastAPI event loop), so they must
use the standard sqlite3 module rather than aiosqlite.
"""
import sqlite3
from pathlib import Path
from api.config import get_settings


def _db_path(slug: str) -> str:
    return str(Path(get_settings().database_dir) / f"{slug}.db")


def get_project_id(slug: str) -> int:
    """Return the integer project id for slug. Raises ValueError if not found."""
    conn = sqlite3.connect(_db_path(slug))
    cur = conn.execute("SELECT id FROM projects WHERE slug=?", (slug,))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise ValueError(f"Project not found: {slug}")
    return row[0]


def insert_agent_output_sync(
    slug: str, agent_name: str, output_type: str, file_path: str
) -> int:
    """Insert an agent_outputs record and return the new row id."""
    project_id = get_project_id(slug)
    conn = sqlite3.connect(_db_path(slug))
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.execute(
        "SELECT MAX(version) FROM agent_outputs WHERE project_id=? AND agent_name=? AND output_type=?",
        (project_id, agent_name, output_type),
    )
    max_ver = cur.fetchone()[0]
    version = (max_ver or 0) + 1
    cur = conn.execute(
        "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path, version)"
        " VALUES (?,?,?,?,?)",
        (project_id, agent_name, output_type, file_path, version),
    )
    conn.commit()
    output_id = cur.lastrowid
    conn.close()
    return output_id


def insert_hitl_review(slug: str, run_id: int, prompt: str) -> int:
    """Insert a human_reviews record with decision='pending'. Returns review_id."""
    conn = sqlite3.connect(_db_path(slug))
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.execute(
        "INSERT INTO human_reviews (crew_run_id, decision, prompt) VALUES (?,?,?)",
        (run_id, "pending", prompt),
    )
    conn.commit()
    review_id = cur.lastrowid
    conn.close()
    return review_id


def get_review_decision(slug: str, review_id: int) -> tuple[str, str]:
    """Return (decision, notes) for a review. Returns ('pending', '') if not found."""
    conn = sqlite3.connect(_db_path(slug))
    cur = conn.execute(
        "SELECT decision, notes FROM human_reviews WHERE id=?", (review_id,)
    )
    row = cur.fetchone()
    conn.close()
    return (row[0], row[1] or "") if row else ("pending", "")


def complete_hitl_review(slug: str, review_id: int, decision: str) -> None:
    """Update decision on a review (used by test_auto_respond mode)."""
    conn = sqlite3.connect(_db_path(slug))
    conn.execute(
        "UPDATE human_reviews SET decision=?, reviewed_at=CURRENT_TIMESTAMP WHERE id=?",
        (decision, review_id),
    )
    conn.commit()
    conn.close()
