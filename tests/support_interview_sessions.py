# tests/support_interview_sessions.py
"""A fixture writer for `interview_sessions`, living where fixture writers belong.

This function was `api.database.insert_interview_session`. CLAUDE.md recorded it as having no
production caller and warned what that costs: "Delete it, or make it the producer; do not leave
both" - and named the precise failure, a branch extending it with a `script_id` column that
production never populated. It happened a second time. `InterviewSessionTool._create` is the
only thing that creates a session, it now writes `interviewer_agent_id` and a resolved
`voice_config`, and the helper had drifted two columns behind - to the point where a session it
created was **refused** by `POST /{token}/speak`, because a session with no stamped voice is a
bug the product now declines to paper over.

It could not be made the producer: the producer is a synchronous CrewAI tool using `sqlite3`
directly, and this is `aiosqlite`. So it is deleted from production and kept here, which is the
half of the rule that could be honoured. Twenty-eight call sites across eleven test files build
sessions with it; they are building fixtures, and a fixture writer that says so cannot drift
away from a production caller it does not have.

**It deliberately does not stamp.** A test that needs a stamped session should say so at its own
call site, and several tests need an *unstamped* one precisely because that is the state the
speak door refuses. A default stamp here would hide that case from the tests that exist to drive
it.
"""
from __future__ import annotations

import aiosqlite


async def insert_interview_session(
    conn: aiosqlite.Connection,
    *,
    project_id: int,
    orchestration_run_id: int | None,
    stakeholder_id: int,
    node_label: str,
    session_token: str,
    voice_config: str | None = None,
    script_id: str | None = None,
    interviewer_agent_id: str | None = None,
) -> int:
    cur = await conn.execute(
        "INSERT INTO interview_sessions "
        "(project_id, orchestration_run_id, stakeholder_id, node_label, session_token,"
        " voice_config, script_id, interviewer_agent_id) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (project_id, orchestration_run_id, stakeholder_id, node_label, session_token,
         voice_config, script_id, interviewer_agent_id),
    )
    await conn.commit()
    return cur.lastrowid
