# agents/tools/_db.py
"""Synchronous SQLite helpers for use inside CrewAI tools.

Tools run in CrewAI's thread pool (not the FastAPI event loop), so they must
use the standard sqlite3 module rather than aiosqlite.
"""
import contextlib
import re
import sqlite3
from pathlib import Path
from api.config import get_settings


def _versioned_path(original: Path, version: int) -> Path:
    """Return a version-stamped sibling path, e.g. value_chain_v2.md."""
    return original.parent / f"{original.stem}_v{version}{original.suffix}"


def latest_output_path(original: Path) -> Path | None:
    """Resolve the newest file written under `original`'s name, or None.

    insert_agent_output_sync renames every output it records to a _vN suffix,
    so after the first write nothing remains at the un-suffixed path. Any code
    reading an output back must resolve through here — reading the base path
    directly silently behaves as though the output had never been written.

    The un-suffixed path is preferred when present, so outputs written before
    versioning existed (or by hand) are still found.
    """
    if original.exists():
        return original

    pattern = re.compile(rf"^{re.escape(original.stem)}_v(\d+){re.escape(original.suffix)}$")
    versions: list[tuple[int, Path]] = []
    for candidate in original.parent.glob(f"{original.stem}_v*{original.suffix}"):
        match = pattern.match(candidate.name)
        if match:
            versions.append((int(match.group(1)), candidate))
    return max(versions)[1] if versions else None


def current_output_path(
    slug: str, output_type: str, *, run_id: int = 0
) -> Path | None:
    """The file the ledger marks current for this output type.

    agent_outputs already records this and already maintains it: insert_agent_output_sync
    sweeps is_current and stores the versioned path, and revert_to_version repoints
    is_current to the reverted version. Reverting is exactly the case a filename-ordering
    scheme cannot express - the newer files are still on disk, and they are not the answer.

    Three outcomes, deliberately distinct:

      row + file exists  -> the file
      row, file missing  -> None, and a warning naming what survives. Falling through to
                            the glob here is what turns a broken pointer into a wrong
                            answer, which is how the 15 July value_chain_summary was read
                            on every run for three weeks, naming a party a human had
                            already corrected.
      no row             -> latest_output_path, which covers a first write (the file is
                            written and renamed before its row exists), a hand-written
                            file, and projects predating versioning.
    """
    settings = get_settings()
    outputs_dir = Path(settings.projects_dir) / slug / "outputs"
    base = outputs_dir / f"{output_type}.json"

    try:
        project_id = get_project_id(slug)
        with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
            row = conn.execute(
                "SELECT version, file_path FROM agent_outputs"
                " WHERE project_id=? AND output_type=? AND is_current=1"
                " ORDER BY version DESC LIMIT 1",
                (project_id, output_type),
            ).fetchone()
    except (sqlite3.Error, ValueError):
        return latest_output_path(base)   # an unreadable ledger is not an answer

    if row is None:
        return latest_output_path(base)

    version, file_path = row[0], Path(row[1])
    if file_path.exists():
        return file_path

    _record_missing_current(slug, output_type, version, file_path, outputs_dir, run_id)
    return None


def _record_missing_current(
    slug: str, output_type: str, version, file_path: Path, outputs_dir: Path, run_id: int
) -> None:
    """Name the output, the version, the missing file, and what is left to revert to.

    The reader has two remedies - revert to a version that still exists, or restore a
    backup by hand - and neither is possible without knowing what survives.
    """
    pattern = re.compile(rf"^{re.escape(output_type)}_v(\d+)\.json$")
    survivors = sorted(
        int(m.group(1))
        for p in outputs_dir.glob(f"{output_type}_v*.json")
        if (m := pattern.match(p.name))
    )
    available = ", ".join(f"v{v}" for v in survivors) if survivors else "none"
    try:
        record_validation_warnings_sync(slug, run_id, "output_resolution", [{
            "subject": output_type,
            "code": "current_file_missing",
            "measure": None,
            "detail": (
                f"{output_type} is marked current at v{version}, but {file_path.name} is "
                f"not on disk. Nothing resolved it to an older version, because reading a "
                f"superseded artefact silently is worse than reading none. Still present: "
                f"{available}. Revert to one of those, or restore the file from a backup."
            ),
        }])
    except Exception:
        pass   # a resolver must not fail because bookkeeping did


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
        # Scoped per (project, output_type) to match the filename, which carries no agent.
        # Scoping the version per agent while the filename ignored the agent is what let one
        # agent's v1 land on another's.
        max_ver = conn.execute(
            "SELECT MAX(version) FROM agent_outputs"
            " WHERE project_id=? AND output_type=?",
            (project_id, output_type),
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
            " WHERE project_id=? AND output_type=?",
            (project_id, output_type),
        )
        cur = conn.execute(
            "INSERT INTO agent_outputs"
            " (project_id, agent_name, output_type, file_path, version, is_current)"
            " VALUES (?,?,?,?,?,1)",
            (project_id, agent_name, output_type, file_path, version),
        )
        conn.commit()
        return cur.lastrowid


def record_blocked_write_sync(
    slug: str, run_id: int, agent_name: str, key: str, owner: str | None, reason: str
) -> None:
    """Best-effort. The refusal is the load-bearing half; if this fails the write is still
    refused, and losing the record is better than letting the write through."""
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        project_id = get_project_id(slug)
        conn.execute(
            "INSERT INTO blocked_writes (project_id, run_id, agent_name, key, owner, reason)"
            " VALUES (?,?,?,?,?,?)",
            (project_id, run_id or None, agent_name, key, owner, reason),
        )
        conn.commit()


def record_run_input_sync(slug: str, run_id: int, agent_name: str, output_id: int) -> None:
    if not run_id or not output_id:
        return
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO run_inputs (run_id, agent_name, output_id) VALUES (?,?,?)",
            (run_id, agent_name, output_id),
        )
        conn.commit()


def record_run_document_sync(slug: str, run_id: int, agent_name: str, doc_id: int) -> None:
    if not run_id or not doc_id:
        return
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO run_documents (run_id, agent_name, doc_id) VALUES (?,?,?)",
            (run_id, agent_name, doc_id),
        )
        conn.commit()


def link_output_sync(slug: str, run_id: int, agent_name: str, output_id: int) -> None:
    """Link a new output to what its OWN writing agent has read SO FAR in this run.

    Scoped by agent_name as well as run_id: a crew run spans several agents
    (discovery_mapping runs value_chain_mapper and value_lever_analyst; discovery_interviews
    runs three), so a read recorded under run_id alone would attach to whatever any agent in
    the run writes next - not just the agent that actually made the read. Taken at write time
    rather than at run end: a read that happens afterwards belongs to whatever is written
    next, and attaching it here would claim this output was built from something that did
    not exist when it was made.
    """
    if not output_id:
        return
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO output_lineage (output_id, input_output_id)"
            " SELECT ?, output_id FROM run_inputs"
            " WHERE run_id=? AND agent_name=? AND output_id != ?",
            (output_id, run_id, agent_name, output_id),
        )
        conn.execute(
            "INSERT OR IGNORE INTO output_citations (output_id, doc_id)"
            " SELECT ?, doc_id FROM run_documents WHERE run_id=? AND agent_name=?",
            (output_id, run_id, agent_name),
        )
        conn.commit()


def output_id_for_path_sync(slug: str, file_path: str) -> int | None:
    """The agent_outputs row for a resolved output file, or None.

    None is normal rather than exceptional: files written by hand, or before versioning
    existed, have no row. A read of one records no lineage edge, which is honest.
    """
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        row = conn.execute(
            "SELECT id FROM agent_outputs WHERE file_path=? ORDER BY id DESC LIMIT 1",
            (file_path,),
        ).fetchone()
    return row[0] if row else None


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


def record_validation_warnings_sync(
    slug: str, run_id: int, source: str, warnings: list[dict], *, complete: bool = False
) -> None:
    """Best-effort, exactly as record_blocked_write_sync is best-effort.

    A validator that warns must never be able to fail the write it was inspecting - the
    whole point of warn-and-record over refuse is that the work survives. Losing a warning
    is strictly better than losing the output that produced it.

    One row per (project, source, subject, code), refreshed on each occurrence.
    `disposition` is deliberately not refreshed: a reviewer's judgement outlives the run
    that triggered it.

    `complete` says this call carries the FULL set of findings for its source, so anything
    absent is no longer true and is cleared. A warner qualifies - it re-derives every
    finding from the artefact it just judged - and run 29 shows why it matters: missing_l0
    was raised on tree v17 and fixed by v18 in the same run, and without clearing the
    reviewer sees a solved problem and the agent is re-injected a warning it already acted
    on. The resolver does NOT qualify: it reports one output at a time, and clearing on its
    behalf would erase a finding about a different output.

    A dismissal survives clearing. It is a standing judgement that this finding is a false
    positive, and if the condition returns that judgement should still apply - which it
    cannot if the row it lives on was deleted the moment the finding stopped appearing. An
    acknowledged warning that has been fixed is deleted: raised, acknowledged, fixed is the
    loop completing, not a record to keep.
    """
    from api.services.anchor_validation import SKEW_RERAISE_DELTA

    if not warnings and not complete:
        return
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        project_id = get_project_id(slug)
        for w in warnings:
            subject = w.get("subject")
            measure = w.get("measure")
            row = conn.execute(
                "SELECT id, disposition, measure FROM validation_warnings"
                " WHERE project_id=? AND source=? AND IFNULL(subject,'')=? AND code=?",
                (project_id, source, subject or "", w["code"]),
            ).fetchone()

            if row is None:
                conn.execute(
                    "INSERT INTO validation_warnings"
                    " (project_id, run_id, source, subject, code, detail, measure)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (project_id, run_id or None, source, subject,
                     w["code"], w["detail"], measure),
                )
                continue

            warning_id, disposition, old_measure = row[0], row[1], row[2]
            # A dismissal says "this is a false positive at this magnitude". Once the
            # magnitude moves materially it is a different claim, so the dismissal expires.
            # Without this one dismissal silences the check forever, which is how a warning
            # system dies. An acknowledgement is never auto-reset - it already says the
            # warning is right, and no measure makes it more so. A warning with no measure
            # has nothing to compare, so its dismissal stands.
            reraise = (
                disposition == "dismissed"
                and measure is not None and old_measure is not None
                and abs(measure - old_measure) > SKEW_RERAISE_DELTA
            )
            if reraise:
                conn.execute(
                    "UPDATE validation_warnings SET run_id=?, detail=?, measure=?,"
                    " disposition='open', disposition_note=NULL, disposed_by=NULL,"
                    " disposed_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (run_id or None, w["detail"], measure, warning_id),
                )
            else:
                conn.execute(
                    "UPDATE validation_warnings SET run_id=?, detail=?, measure=?,"
                    " updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (run_id or None, w["detail"], measure, warning_id),
                )

        if complete:
            seen = [(w.get("subject") or "", w["code"]) for w in warnings]
            sql = (
                "DELETE FROM validation_warnings"
                " WHERE project_id=? AND source=?"
                "   AND disposition IN ('open','acknowledged')"
            )
            params: list = [project_id, source]
            if seen:
                pairs = " OR ".join(["(IFNULL(subject,'')=? AND code=?)"] * len(seen))
                sql += f" AND NOT ({pairs})"
                for subject, code in seen:
                    params.extend([subject, code])
            conn.execute(sql, params)
        conn.commit()


def current_script_ledger_sync(slug: str) -> dict:
    """The script ledger in force, in the shape the scripts-door guard already consumes.

    Returning {"scripts": [...]} rather than a friendlier shape is deliberate:
    validate_scripts_against_script_registry stays a pure function over a mapping and does
    not change at all, so moving the ledger from a file to a table has no blast radius
    beyond the loader.
    """
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        rows = conn.execute(
            "SELECT script_id, node_id, active FROM interview_script_ledger"
        ).fetchall()
    return {"scripts": [{"id": r[0], "node_id": r[1], "active": bool(r[2])} for r in rows]}


def register_scripts_sync(slug: str, scripts: dict, version: int, author: str) -> int:
    """Register any script id not already held. Returns how many were added.

    INSERT OR IGNORE, never UPDATE of node_id. That is what makes automatic registration
    safe: the succession rule forbids exactly two things, redefining an id and dropping
    one, and appending does neither. A batch that moves a registered id is refused by the
    validator before this ever runs, so the ledger cannot be talked into agreeing with it.

    last_version and last_author are refreshed for every id in the batch, including ids
    already registered, because they record which version last changed this script and
    who wrote it - which is a different question from where the id is anchored.
    """
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        row = conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)).fetchone()
        if not row:
            raise ValueError(f"Project not found: {slug}")
        project_id = row[0]
        added = 0
        for key, script in scripts.items():
            if not isinstance(script, dict):
                continue
            script_id = script.get("script_id") or key
            node_id = script.get("node_id")
            if not script_id or not node_id:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO interview_script_ledger"
                " (script_id, project_id, node_id, node_label, last_version, last_author)"
                " VALUES (?,?,?,?,?,?)",
                (script_id, project_id, node_id, script.get("node_label", ""),
                 version, author),
            )
            added += cur.rowcount
            conn.execute(
                "UPDATE interview_script_ledger"
                " SET last_version=?, last_author=?, updated_at=CURRENT_TIMESTAMP"
                " WHERE script_id=?",
                (version, author, script_id),
            )
        conn.commit()
    return added


def _output_version_sync(slug: str, output_id: int) -> int:
    """The version of one agent_outputs row, or 0 if it has gone."""
    with contextlib.closing(sqlite3.connect(_db_path(slug))) as conn:
        row = conn.execute(
            "SELECT version FROM agent_outputs WHERE id=?", (output_id,)
        ).fetchone()
    return row[0] if row else 0
