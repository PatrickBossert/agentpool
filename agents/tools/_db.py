# agents/tools/_db.py
"""Synchronous SQLite helpers for use inside CrewAI tools.

Tools run in CrewAI's thread pool (not the FastAPI event loop), so they must
use the standard sqlite3 module rather than aiosqlite.
"""
import contextlib
import sqlite3
from pathlib import Path
from api.config import get_settings


def _db_path(slug: str) -> str:
    return str(Path(get_settings().database_dir) / f"{slug}.db")


def get_project_id(slug: str) -> int:
    """Return the integer project id for slug. Raises ValueError if not found."""
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        row = conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)).fetchone()
    if not row:
        raise ValueError(f"Project not found: {slug}")
    return row[0]


def insert_agent_output_sync(
    slug: str, agent_name: str, output_type: str, file_path: str
) -> int:
    """Insert an agent_outputs record and return the new row id."""
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        row = conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)).fetchone()
        if not row:
            raise ValueError(f"Project not found: {slug}")
        project_id = row[0]
        max_ver = conn.execute(
            "SELECT MAX(version) FROM agent_outputs"
            " WHERE project_id=? AND agent_name=? AND output_type=?",
            (project_id, agent_name, output_type),
        ).fetchone()[0]
        version = (max_ver or 0) + 1
        cur = conn.execute(
            "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path, version)"
            " VALUES (?,?,?,?,?)",
            (project_id, agent_name, output_type, file_path, version),
        )
        conn.commit()
        return cur.lastrowid


def insert_hitl_review(slug: str, run_id: int, prompt: str) -> int:
    """Insert a human_reviews record with decision='pending'. Returns review_id."""
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.execute(
            "INSERT INTO human_reviews (crew_run_id, decision, prompt) VALUES (?,?,?)",
            (run_id, "pending", prompt),
        )
        conn.commit()
        return cur.lastrowid


def get_review_decision(slug: str, review_id: int) -> tuple[str, str]:
    """Return (decision, notes) for a review. Returns ('pending', '') if not found."""
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        row = conn.execute(
            "SELECT decision, notes FROM human_reviews WHERE id=?", (review_id,)
        ).fetchone()
    return (row[0], row[1] or "") if row else ("pending", "")


def complete_hitl_review(slug: str, review_id: int, decision: str) -> None:
    """Update decision on a review (used by test_auto_respond mode)."""
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        conn.execute(
            "UPDATE human_reviews SET decision=?, reviewed_at=CURRENT_TIMESTAMP WHERE id=?",
            (decision, review_id),
        )
        conn.commit()
