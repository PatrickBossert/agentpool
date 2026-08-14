# tests/test_session_script_citation.py
"""An answer learns which instrument produced it from the session, not from label text.

script_for_session used to resolve script_id by matching node_template_assignments on
node_label - the same label matching that makes publish_node_template 404 against an artefact
keyed by script_id. A session is *for* a script, so the session carries it.

**These tests drive InterviewSessionTool, not api.database.insert_interview_session.** The
first version of this file drove the helper, which has no production caller at all: the only
code in api/ or agents/ that inserts an interview_sessions row is InterviewSessionTool._create,
and its INSERT named six columns with script_id not among them. So the helper round-tripped a
script_id nothing ever stored, every real session carried NULL, and answers were cited by the
label scan the column exists to replace. The producer is the thing to drive.
"""
import contextlib
import json
import sqlite3
from unittest.mock import patch

import pytest

# Two scripts sharing a node_label, so a label match cannot pick the right one.
TWO_SHARED_LABEL_SCRIPTS = {
    "SC-001": {"script_id": "SC-001", "node_id": "1.2", "node_label": "Shared", "sections": []},
    "SC-002": {"script_id": "SC-002", "node_id": "1.3", "node_label": "Shared", "sections": []},
}


async def _seed(tmp_path, slug: str, scripts: dict) -> None:
    """A project, a stakeholder, an orchestration run and a crew run, plus a current
    interview_scripts artefact - the state InterviewSessionTool.create runs against.

    get_connection is what runs the schema migrations, interview_sessions.script_id among
    them, so the tool's own sqlite3 connection finds the column already there.
    """
    from api.config import get_settings
    from api.database import get_connection
    from agents.tools._db import insert_agent_output_sync

    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "interview_scripts.json").write_text(json.dumps(scripts))

    async with get_connection(slug) as conn:
        await conn.execute("INSERT INTO projects (slug) VALUES (?)", (slug,))
        await conn.execute("INSERT INTO stakeholders (project_id, name) VALUES (1, 'Ana')")
        await conn.execute("INSERT INTO orchestration_runs (project_id) VALUES (1)")
        await conn.execute(
            "INSERT INTO crew_runs (project_id, crew_name, orchestration_run_id)"
            " VALUES (1, 'discovery_interviews', 1)")
        await conn.commit()
    insert_agent_output_sync(slug=slug, agent_name="interaction_designer",
                             output_type="interview_scripts",
                             file_path=str(outputs / "interview_scripts.json"))
    get_settings()  # settings are already cached against tmp_path; kept explicit for clarity


def _create_session(slug: str, session: dict) -> str:
    from agents.tools.interview_session_tool import InterviewSessionTool
    tool = InterviewSessionTool(slug=slug, orchestration_run_id=1)
    with patch("api.services.interview_service.get_settings") as ms:
        ms.return_value.public_url = "https://app.example.com"
        return tool._run(operation="create", sessions=[session], session_tokens=[])


def _stored_session(tmp_path, slug: str) -> dict:
    with contextlib.closing(sqlite3.connect(str(tmp_path / "db" / f"{slug}.db"))) as conn:
        conn.row_factory = sqlite3.Row
        return dict(conn.execute("SELECT * FROM interview_sessions").fetchone())


@pytest.mark.asyncio
async def test_the_tool_stores_the_script_the_plan_named(tmp_path, monkeypatch):
    """The load-bearing claim: script_id is set when the session is created.

    Asserted on the stored row and then on the resolution, because the two fail
    independently - a resolution test alone passes on a hand-inserted row that the
    production path never produces.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "db"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        from api.database import get_connection
        from api.services.interview_answer_service import script_for_session

        slug = "sess-cite"
        await _seed(tmp_path, slug, TWO_SHARED_LABEL_SCRIPTS)
        result = _create_session(
            slug, {"stakeholder_id": 1, "name": "Ana", "node_label": "Shared",
                   "script_id": "SC-002"})
        assert result.startswith("Sessions created"), result

        session = _stored_session(tmp_path, slug)
        assert session["script_id"] == "SC-002", (
            "the plan named SC-002; a session that stores NULL sends every answer back "
            "through the label scan this column exists to replace"
        )

        async with get_connection(slug) as conn:
            script = await script_for_session(conn, slug, session)
        assert script is not None
        assert script["script_id"] == "SC-002", (
            "the session named SC-002; a label match would have returned whichever of the "
            "two shared scripts came first"
        )
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_an_omitted_script_id_is_resolved_in_code_when_the_label_is_unambiguous(
        tmp_path, monkeypatch):
    """A plan entry with no script_id still produces a session that carries one.

    The coordinator's prompt now asks for script_id, but a prompt is a request, not a
    guarantee, and a silently-NULL column is exactly the failure this branch was built to
    end. Where the label picks out exactly one script, the tool resolves it from the current
    artefact - the same resolution the downstream fallback would do, done once and recorded.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "db"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        slug = "sess-resolve"
        await _seed(tmp_path, slug, {
            "SC-001": {"script_id": "SC-001", "node_id": "1.2",
                       "node_label": "Goods-in", "sections": []},
            "SC-002": {"script_id": "SC-002", "node_id": "1.3",
                       "node_label": "Packing", "sections": []},
        })
        _create_session(slug, {"stakeholder_id": 1, "name": "Ana", "node_label": "Packing"})
        assert _stored_session(tmp_path, slug)["script_id"] == "SC-002"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_an_ambiguous_label_stores_no_script_id_rather_than_a_guess(
        tmp_path, monkeypatch):
    """Two scripts share the label and the plan named neither, so there is no answer.

    Storing whichever one came first would be indistinguishable, downstream, from a session
    that genuinely named that script - a wrong citation nothing can later detect. NULL is
    recoverable; a confident wrong id is not.

    The resolution is asserted too, and it is the same refusal for the same reason: the
    label scan is only an answer where the label picks out one script.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "db"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        from api.database import get_connection
        from api.services.interview_answer_service import script_for_session

        slug = "sess-ambiguous"
        await _seed(tmp_path, slug, TWO_SHARED_LABEL_SCRIPTS)
        _create_session(slug, {"stakeholder_id": 1, "name": "Ana", "node_label": "Shared"})
        session = _stored_session(tmp_path, slug)
        assert session["script_id"] is None

        async with get_connection(slug) as conn:
            assert await script_for_session(conn, slug, session) is None, (
                "two scripts carry this label and the session names neither - the scan has "
                "no answer, and its first match is a guess"
            )
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_session_naming_a_script_the_artefact_lost_is_not_resolved_by_label(
        tmp_path, monkeypatch):
    """The docstring's promise, which the code did not keep.

    script_for_session said it "returns None rather than guessing", then fell through from a
    failed script_id lookup into the node_label scan and guessed. A session that names a
    script the current artefact no longer holds is a session whose instrument is gone - a
    same-labelled neighbour is not it.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "db"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        from api.database import get_connection
        from api.services.interview_answer_service import script_for_session

        slug = "sess-retired"
        await _seed(tmp_path, slug, {
            "SC-001": {"script_id": "SC-001", "node_id": "1.2",
                       "node_label": "Shared", "sections": []},
        })
        _create_session(slug, {"stakeholder_id": 1, "name": "Ana", "node_label": "Shared",
                               "script_id": "SC-999"})
        session = _stored_session(tmp_path, slug)
        assert session["script_id"] == "SC-999"

        async with get_connection(slug) as conn:
            script = await script_for_session(conn, slug, session)
        assert script is None, (
            "SC-999 is not in the artefact; SC-001 merely shares its label"
        )
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_session_predating_the_column_still_resolves_by_label(tmp_path, monkeypatch):
    """The label scan stays, for the rows it was the only answer for.

    Sessions created before script_id existed carry NULL and were keyed on node_label. They
    resolve by label - but only where the label picks out exactly one script, because two
    matches is not an answer either.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "db"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        from api.database import get_connection
        from api.services.interview_answer_service import script_for_session

        slug = "sess-legacy"
        await _seed(tmp_path, slug, {
            "SC-001": {"script_id": "SC-001", "node_id": "1.2",
                       "node_label": "Goods-in", "sections": []},
        })
        _create_session(slug, {"stakeholder_id": 1, "name": "Ana", "node_label": "Goods-in"})
        async with get_connection(slug) as conn:
            await conn.execute("UPDATE interview_sessions SET script_id=NULL")
            await conn.commit()
        session = _stored_session(tmp_path, slug)
        assert session["script_id"] is None

        async with get_connection(slug) as conn:
            script = await script_for_session(conn, slug, session)
        assert script is not None
        assert script["script_id"] == "SC-001"
    finally:
        get_settings.cache_clear()
