# tests/test_interview_concurrency.py
"""Properties that only exist when interviews overlap.

Asserted against behaviour rather than against call sites. A test that asserts
asyncio.to_thread was called cannot tell whether the event loop was actually freed,
which is the entire property.
"""
import asyncio
import json
import time

import pytest
import pytest_asyncio


@pytest.mark.asyncio
async def test_indexing_does_not_delay_other_sessions(monkeypatch):
    """One session completing must not stall the others.

    index_answers is stubbed with a blocking sleep standing in for a slow or unreachable
    Chroma. If it runs on the event loop, the concurrent waiter is served only after it
    finishes; if it runs in a thread, the waiter is served immediately.
    """
    from api.services import interview_answer_service as svc

    def slow_index(slug, rows):
        time.sleep(0.5)          # blocking, exactly as a Chroma round trip is
        return len(rows)

    monkeypatch.setattr(svc, "index_answers", slow_index)

    async def waiter(t0):
        await asyncio.sleep(0.01)
        return time.perf_counter() - t0

    t0 = time.perf_counter()
    _, waited = await asyncio.gather(
        svc._index_in_background("s", [{"id": 1}]),
        waiter(t0),
    )
    assert waited < 0.2, (
        f"a concurrent session waited {waited:.2f}s while another completed - "
        "indexing is still on the event loop"
    )


@pytest_asyncio.fixture
async def dup_project(tmp_path, monkeypatch):
    """A project with a versioned scripts artefact and one session, wired to the ledger.

    Same fixture shape as test_interview_service.py's served_project - a project row, a
    current interview_scripts artefact resolvable via current_output_path, a stakeholder,
    and a pending session - but keyed for a session_token this file's tests submit against
    repeatedly.
    """
    from api.config import get_settings

    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "dupproj"
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True)

    scripts = {"SC-001": {"script_id": "SC-001", "node_id": "1.F",
                          "node_label": "Frontline Interview", "level": "F",
                          "relationship": "internal", "sections": []}}
    (outputs / "interview_scripts_v1.json").write_text(json.dumps(scripts))

    from api.database import get_connection
    async with get_connection(slug) as conn:
        await conn.execute("INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
        cur = await conn.execute("SELECT id FROM projects WHERE slug=?", (slug,))
        pid = (await cur.fetchone())[0]
        await conn.execute(
            "INSERT INTO agent_outputs (project_id, agent_name, output_type, "
            "version, is_current, file_path) VALUES (?,?,?,?,?,?)",
            (pid, "interaction_designer", "interview_scripts", 1, 1,
             str(outputs / "interview_scripts_v1.json")),
        )
        await conn.execute(
            "INSERT INTO stakeholders (project_id, name) VALUES (?,?)", (pid, "Sam Stakeholder"),
        )
        await conn.commit()
        cur = await conn.execute("SELECT id FROM stakeholders WHERE project_id=?", (pid,))
        sid = (await cur.fetchone())[0]
        await conn.execute(
            "INSERT INTO interview_sessions (project_id, stakeholder_id, node_label, "
            "session_token, status) VALUES (?,?,?,?,?)",
            (pid, sid, "Frontline Interview", "dup-token", "pending"),
        )
        await conn.commit()
    yield slug
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_completing_twice_writes_one_answer_set(client, dup_project):
    """Driven through the endpoint twice, not by calling record_answers twice.

    The constraint lives on the table but the guard lives in the endpoint, and CLAUDE.md
    records five occasions where a test verified a property one layer from where it holds.
    """
    pairs = [{"question_id": "q1", "question": "Q one?", "answer": "A one"},
             {"question_id": "q2", "question": "Q two?", "answer": "A two"}]
    for _ in range(2):
        r = await client.patch("/api/interviews/dup-token/complete", json={"qa_pairs": pairs})
        assert r.status_code == 200

    from api.database import get_connection
    async with get_connection("dupproj") as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM interview_answers WHERE session_id="
            "(SELECT id FROM interview_sessions WHERE session_token='dup-token')"
        )
        assert (await cur.fetchone())[0] == 2, "the second completion duplicated the corpus"


@pytest.mark.asyncio
async def test_a_changed_resubmission_keeps_its_citation_id(client, dup_project):
    """id is the citation token retrieved chunks carry - a resubmission must not mint a new
    one, or a citation issued against the first submission would point at nothing."""
    first = [{"question_id": "q1", "question": "Q one?", "answer": "A one"}]
    r = await client.patch("/api/interviews/dup-token/complete", json={"qa_pairs": first})
    assert r.status_code == 200

    from api.database import get_connection
    async with get_connection("dupproj") as conn:
        cur = await conn.execute(
            "SELECT id FROM interview_answers WHERE session_id="
            "(SELECT id FROM interview_sessions WHERE session_token='dup-token') "
            "AND question_id='q1'"
        )
        original_id = (await cur.fetchone())[0]

    revised = [{"question_id": "q1", "question": "Q one?", "answer": "A one, revised"}]
    r = await client.patch("/api/interviews/dup-token/complete", json={"qa_pairs": revised})
    assert r.status_code == 200

    async with get_connection("dupproj") as conn:
        cur = await conn.execute(
            "SELECT id, answer_text FROM interview_answers WHERE session_id="
            "(SELECT id FROM interview_sessions WHERE session_token='dup-token') "
            "AND question_id='q1'"
        )
        row = await cur.fetchone()

    assert row[0] == original_id, "resubmission minted a new id - a citation would break"
    assert row[1] == "A one, revised", "resubmission did not update the answer text"
