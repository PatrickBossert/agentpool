# agents/tools/_db.py
"""Synchronous SQLite helpers for use inside CrewAI tools.

Tools run in CrewAI's thread pool (not the FastAPI event loop), so they must
use the standard sqlite3 module rather than aiosqlite.
"""
import contextlib
import sqlite3
from pathlib import Path
from api.config import get_settings


def _versioned_path(original: Path, version: int) -> Path:
    """Return a version-stamped sibling path, e.g. value_chain_v2.md."""
    return original.parent / f"{original.stem}_v{version}{original.suffix}"


def _db_path(slug: str) -> str:
    return str(Path(get_settings().database_dir) / f"{slug}.db")


_CREW_TO_AGENTS: dict[str, list[str]] = {
    "discovery_mapping":      ["value_chain_mapper"],
    "assessment_design":      ["interaction_designer"],
    "discovery":              ["requirements_capture", "requirements_analyst", "value_lever_analyst"],
    "stakeholder_management": ["stakeholder_manager"],
    "discovery_interviews":   ["interview_coordinator", "stakeholder_interviewer", "synthesis_analyst"],
    "value_design":           ["value_proposition_generator", "portfolio_manager"],
    "architecture":           ["enterprise_architect", "initiative_identifier"],
    "delivery":               ["roadmap_generator"],
    "business_plan":          ["business_plan_generator"],
}


def _extract_revision_body(prompt: str) -> str:
    """Strip 'Please review…' header and 'Reply approved…' footer from a HITL prompt."""
    lines = prompt.strip().splitlines()
    if lines and lines[0].lower().startswith("please review"):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and "reply" in lines[-1].lower() and "approved" in lines[-1].lower():
        lines.pop()
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip()


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
    """Insert a versioned agent_outputs record and return the new row id.

    The output file is renamed on disk to include the version suffix
    (e.g. value_chain.md → value_chain_v2.md) so that all versions are
    preserved for history and revert. Any adjacent file with the same stem
    but .svg extension is renamed in lockstep.
    """
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

        # Rename the output file to its versioned path
        original = Path(file_path)
        versioned = _versioned_path(original, version)
        if original.exists():
            original.rename(versioned)
            # Rename adjacent SVG if present (e.g. Mermaid diagrams)
            svg_orig = original.with_suffix(".svg")
            if svg_orig.exists():
                svg_orig.rename(versioned.with_suffix(".svg"))
            file_path = str(versioned)

        # Mark all previous versions of this output as superseded
        conn.execute(
            "UPDATE agent_outputs SET is_current=0"
            " WHERE project_id=? AND agent_name=? AND output_type=?",
            (project_id, agent_name, output_type),
        )
        cur = conn.execute(
            "INSERT INTO agent_outputs"
            " (project_id, agent_name, output_type, file_path, version, is_current)"
            " VALUES (?,?,?,?,?,1)",
            (project_id, agent_name, output_type, file_path, version),
        )
        conn.commit()
        return cur.lastrowid


def insert_hitl_review(slug: str, run_id: int, prompt: str) -> int:
    """Insert a human_reviews record with decision='pending'. Returns review_id.

    If the prompt contains a revision summary (body text after stripping the standard
    'Please review…' header and 'Reply approved…' footer), that summary is written
    to revision_notes on every is_current output for this crew's agents.
    """
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.execute(
            "INSERT INTO human_reviews (crew_run_id, decision, prompt) VALUES (?,?,?)",
            (run_id, "pending", prompt),
        )
        review_id = cur.lastrowid

        body = _extract_revision_body(prompt)
        if body:
            row = conn.execute(
                "SELECT crew_name, project_id FROM crew_runs WHERE id=?", (run_id,)
            ).fetchone()
            if row:
                crew_name, project_id = row[0], row[1]
                agent_names = _CREW_TO_AGENTS.get(crew_name, [])
                if agent_names:
                    placeholders = ",".join("?" * len(agent_names))
                    conn.execute(
                        f"UPDATE agent_outputs SET revision_notes=?"
                        f" WHERE project_id=? AND agent_name IN ({placeholders}) AND is_current=1",
                        [body, project_id, *agent_names],
                    )

        conn.commit()
        return review_id


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
