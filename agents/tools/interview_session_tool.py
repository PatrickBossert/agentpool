# agents/tools/interview_session_tool.py
"""CrewAI tool wrapping the interview_sessions DB table with four operations.

Runs synchronously (CrewAI thread pool) using sqlite3 directly.

IMPORTANT: The tool's orchestration_run_id field receives the crew_run_id from
the registry. The tool resolves the actual orchestration_run_id from crew_runs
at runtime, so queries against interview_sessions use the correct FK.
"""
import contextlib
import json
import sqlite3
import uuid
from pathlib import Path
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings


def _db_path(slug: str) -> str:
    return str(Path(get_settings().database_dir) / f"{slug}.db")


def _script_ids_by_label(slug: str) -> dict[str, list[str]]:
    """Every script id in the current interview_scripts artefact, grouped by node_label.

    A list per label, not a single id: two scripts can normalise to the same label, which is
    the whole reason interview_sessions carries a script_id at all. Grouping keeps that
    ambiguity visible to the caller instead of resolving it by dictionary order.

    Resolved through the ledger (current_output_path), never by globbing the outputs
    directory - CLAUDE.md's output-resolution rule, and the file this reads is the same one
    interview_answer_service.script_for_session reads later, so a session cannot be stamped
    with an id that artefact does not hold.

    A missing or unreadable artefact yields {}, which simply means nothing can be resolved in
    code and any script_id the plan supplied is used as given.
    """
    from agents.tools._db import current_output_path

    path = current_output_path(slug, "interview_scripts")
    if path is None:
        return {}
    try:
        scripts = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(scripts, dict):
        return {}

    index: dict[str, list[str]] = {}
    for script_id, script in scripts.items():
        if not isinstance(script, dict):
            continue
        label = script.get("node_label")
        if isinstance(label, str) and label:
            index.setdefault(label, []).append(script_id)
    return index


def _resolve_script_id(
    supplied: str | None, node_label: str, by_label: dict[str, list[str]]
) -> str | None:
    """Which script this session is for, preferring what the plan named.

    The Interview Coordinator reads the interview_scripts map keyed by script_id and now
    emits that key in each plan entry, so `supplied` is the ordinary path and it is trusted
    as given - the plan may legitimately name a script whose label was since rewritten.

    A prompt is a request rather than a guarantee, though, and a silently-NULL script_id is
    exactly the failure this column exists to end: every answer would fall back to the label
    scan, which cannot tell two same-labelled scripts apart. So an omitted id is resolved
    here, in code, from the label - but only where the label picks out exactly one script.
    Where it picks out two, there is no answer, and NULL is the honest one: a confident wrong
    id is indistinguishable downstream from a session that genuinely named that script, and
    nothing later can detect it.
    """
    if supplied:
        return supplied
    candidates = by_label.get(node_label, [])
    return candidates[0] if len(candidates) == 1 else None


class InterviewSessionToolInput(BaseModel):
    operation: str = Field(
        description="'create' | 'get_status' | 'get_transcripts' | 'mark_abandoned'"
    )
    sessions: list[dict] = Field(
        default=[],
        description=(
            "For 'create': list of {stakeholder_id, name, node_label, script_id}. "
            "script_id is the key the interview_scripts map holds this stakeholder's script "
            "under - it is what every answer from the session is later cited by, and a "
            "node_label is not unique enough to recover it afterwards. "
            "session_token is assigned in code when the row is created, not supplied here."
        ),
    )
    session_tokens: list[str] = Field(
        default=[],
        description="For 'mark_abandoned': list of session tokens to abandon",
    )


class InterviewSessionTool(BaseTool):
    name: str = "InterviewSessionTool"
    description: str = (
        "Manage interview sessions in the database. "
        "Operations: 'create' (insert sessions, returns URL list), "
        "'get_status' (returns pending/active/completed/abandoned counts), "
        "'get_transcripts' (returns completed transcript JSON), "
        "'mark_abandoned' (marks listed tokens as abandoned)."
    )
    args_schema: type[BaseModel] = InterviewSessionToolInput
    slug: str
    orchestration_run_id: int  # Receives crew_run_id; resolves actual orch_run_id at runtime

    def _run(self, operation: str, sessions: list[dict], session_tokens: list[str]) -> str:
        try:
            db = _db_path(self.slug)

            with contextlib.closing(sqlite3.connect(db)) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys = ON")

                # Get project_id
                row = conn.execute("SELECT id FROM projects WHERE slug=?", (self.slug,)).fetchone()
                if not row:
                    return f"Error: project '{self.slug}' not found"
                project_id = row["id"]

                # Resolve actual orchestration_run_id from crew_run_id
                orch_row = conn.execute(
                    "SELECT orchestration_run_id FROM crew_runs WHERE id=?",
                    (self.orchestration_run_id,),
                ).fetchone()
                actual_orch_id = (
                    orch_row["orchestration_run_id"]
                    if (orch_row and orch_row["orchestration_run_id"])
                    else self.orchestration_run_id
                )

                if operation == "create":
                    return self._create(conn, project_id, actual_orch_id, sessions)
                elif operation == "get_status":
                    return self._get_status(conn, actual_orch_id)
                elif operation == "get_transcripts":
                    return self._get_transcripts(conn, actual_orch_id)
                elif operation == "mark_abandoned":
                    return self._mark_abandoned(conn, session_tokens)
                else:
                    return f"Error: unknown operation '{operation}'"
        except sqlite3.Error as e:
            return f"Error: database error — {e}"

    def _create(
        self,
        conn: sqlite3.Connection,
        project_id: int,
        orchestration_run_id: int,
        sessions: list[dict],
    ) -> str:
        # Imported here, not at module scope: api.services.interview_service pulls in
        # api.database and friends, and this tool module loads early via the CrewAI tool
        # registry - importing at the top risks a circular import. This is the established
        # pattern for this tool.
        from api.services.interview_service import interview_url

        # Read once for the whole batch rather than per session - it is the same file for
        # every row, and the labels-to-ids index below is built from it.
        by_label = _script_ids_by_label(self.slug)

        urls = []
        for s in sessions:
            try:
                stakeholder_id = s["stakeholder_id"]
                node_label = s["node_label"]
            except KeyError as e:
                return f"Error: session dict missing required key {e}"
            # The session token is the sole credential for the public interview API, so
            # its uniqueness must not depend on a language model. Minted here, in code,
            # regardless of anything the caller supplies.
            session_token = str(uuid.uuid4())
            voice_config = s.get("voice_config")
            voice_config_json = json.dumps(voice_config) if voice_config else None
            script_id = _resolve_script_id(s.get("script_id"), node_label, by_label)
            conn.execute(
                "INSERT OR IGNORE INTO interview_sessions "
                "(project_id, orchestration_run_id, stakeholder_id, node_label, session_token,"
                " voice_config, script_id) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    project_id,
                    orchestration_run_id,
                    stakeholder_id,
                    node_label,
                    session_token,
                    voice_config_json,
                    script_id,
                ),
            )
            url = interview_url(session_token)
            urls.append(f"- {s.get('name', 'Stakeholder')}: {url}")
        conn.commit()
        return "Sessions created. Interview URLs:\n" + "\n".join(urls)

    def _get_status(self, conn: sqlite3.Connection, orchestration_run_id: int) -> str:
        counts = {"pending": 0, "active": 0, "completed": 0, "abandoned": 0}
        rows = conn.execute(
            "SELECT status, COUNT(*) as n FROM interview_sessions "
            "WHERE orchestration_run_id=? GROUP BY status",
            (orchestration_run_id,),
        ).fetchall()
        for row in rows:
            if row["status"] in counts:
                counts[row["status"]] = row["n"]
        total = sum(counts.values())
        return (
            f"Status summary ({total} sessions): "
            f"pending={counts['pending']}, active={counts['active']}, "
            f"completed={counts['completed']}, abandoned={counts['abandoned']}"
        )

    def _get_transcripts(self, conn: sqlite3.Connection, orchestration_run_id: int) -> str:
        rows = conn.execute(
            "SELECT s.name, is_.stakeholder_id, is_.node_label, is_.transcript_json "
            "FROM interview_sessions is_ "
            "JOIN stakeholders s ON s.id = is_.stakeholder_id "
            "WHERE is_.orchestration_run_id=? AND is_.status='completed'",
            (orchestration_run_id,),
        ).fetchall()
        results = []
        for row in rows:
            raw = row["transcript_json"]
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = None
            results.append({
                "stakeholder_id": row["stakeholder_id"],
                "name": row["name"],
                "node_label": row["node_label"],
                "transcript_json": parsed,
            })
        return json.dumps(results)

    def _mark_abandoned(self, conn: sqlite3.Connection, session_tokens: list[str]) -> str:
        missed = []
        for token in session_tokens:
            cur = conn.execute(
                "UPDATE interview_sessions SET status='abandoned' WHERE session_token=?",
                (token,),
            )
            if cur.rowcount == 0:
                missed.append(token)
        conn.commit()
        msg = f"Marked {len(session_tokens) - len(missed)} session(s) as abandoned."
        if missed:
            msg += f" Warning: {len(missed)} token(s) not found: {missed}"
        return msg
