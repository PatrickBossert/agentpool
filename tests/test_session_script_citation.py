# tests/test_session_script_citation.py
"""An answer learns which instrument produced it from the session, not from label text.

script_for_session used to resolve script_id by matching node_template_assignments on
node_label - the same label matching that makes publish_node_template 404 against an artefact
keyed by script_id. A session is *for* a script, so the session carries it.
"""
import json
import pytest
from pathlib import Path


@pytest.mark.asyncio
async def test_an_answer_resolves_its_script_from_the_session(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "db"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    from api.config import get_settings
    get_settings.cache_clear()
    try:
        from api.database import get_connection, insert_interview_session
        from api.services.interview_answer_service import script_for_session
        from agents.tools._db import insert_agent_output_sync

        slug = "sess-cite"
        outputs = tmp_path / "projects" / slug / "outputs"
        outputs.mkdir(parents=True, exist_ok=True)
        # Two scripts sharing a node_label, so a label match cannot pick the right one.
        scripts = {
            "SC-001": {"script_id": "SC-001", "node_id": "1.2", "node_label": "Shared", "sections": []},
            "SC-002": {"script_id": "SC-002", "node_id": "1.3", "node_label": "Shared", "sections": []},
        }
        (outputs / "interview_scripts.json").write_text(json.dumps(scripts))

        async with get_connection(slug) as conn:
            await conn.execute("INSERT INTO projects (slug) VALUES (?)", (slug,))
            await conn.execute(
                "INSERT INTO stakeholders (project_id, name) VALUES (1, 'Ana')")
            await conn.commit()
            insert_agent_output_sync(slug=slug, agent_name="interaction_designer",
                                     output_type="interview_scripts",
                                     file_path=str(outputs / "interview_scripts.json"))
            sid = await insert_interview_session(
                conn, project_id=1, orchestration_run_id=None, stakeholder_id=1,
                node_label="Shared", session_token="tok-1", script_id="SC-002")
            conn.row_factory = __import__("aiosqlite").Row
            cur = await conn.execute("SELECT * FROM interview_sessions WHERE id=?", (sid,))
            session = dict(await cur.fetchone())
            # script_for_session's real signature is (conn, slug, session) - the brief's
            # (conn, session, slug) does not match the production call sites in
            # api/services/interview_service.py, so the call order below follows the code.
            script = await script_for_session(conn, slug, session)

        assert script is not None
        assert script["script_id"] == "SC-002", (
            "the session named SC-002; a label match would have returned whichever of the two "
            "shared scripts came first"
        )
    finally:
        get_settings.cache_clear()
