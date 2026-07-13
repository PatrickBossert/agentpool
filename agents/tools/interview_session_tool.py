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
from pathlib import Path
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings


def _db_path(slug: str) -> str:
    return str(Path(get_settings().database_dir) / f"{slug}.db")


class InterviewSessionToolInput(BaseModel):
    operation: str = Field(
        description="'create' | 'get_status' | 'get_transcripts' | 'mark_abandoned'"
    )
    sessions: list[dict] = Field(
        default=[],
        description="For 'create': list of {stakeholder_id, name, node_label, session_token}",
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
        settings = get_settings()
        base_url = settings.frontend_url.rstrip("/")
        urls = []
        for s in sessions:
            try:
                stakeholder_id = s["stakeholder_id"]
                node_label = s["node_label"]
                session_token = s["session_token"]
            except KeyError as e:
                return f"Error: session dict missing required key {e}"
            voice_config = s.get("voice_config")
            voice_config_json = json.dumps(voice_config) if voice_config else None
            conn.execute(
                "INSERT OR IGNORE INTO interview_sessions "
                "(project_id, orchestration_run_id, stakeholder_id, node_label, session_token, voice_config) "
                "VALUES (?,?,?,?,?,?)",
                (
                    project_id,
                    orchestration_run_id,
                    stakeholder_id,
                    node_label,
                    session_token,
                    voice_config_json,
                ),
            )
            url = f"{base_url}/interview/{session_token}"
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
