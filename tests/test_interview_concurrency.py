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


# ---------------------------------------------------------------------------
# Twenty sessions, at once, through the real endpoints.
# ---------------------------------------------------------------------------

from dataclasses import dataclass


@dataclass
class Campaign:
    slug: str
    tokens: list[str]


@pytest_asyncio.fixture
async def seeded_campaign(tmp_path, monkeypatch):
    """One project, twenty pending sessions, and a current interview_scripts artefact.

    Every session points at the same script, which is what a real cohort looks like: twenty
    frontline staff on SC-001, all invited on the same day.
    """
    from api.config import get_settings

    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "peak"
    outputs = tmp_path / "projects" / slug / "outputs"
    outputs.mkdir(parents=True)
    scripts = {"SC-001": {"script_id": "SC-001", "node_id": "1.F",
                          "node_label": "Frontline Interview", "level": "F",
                          "relationship": "internal",
                          "sections": [{"section_id": "s1", "questions": [
                              {"question_id": "q1", "text": "Q?"}]}]}}
    (outputs / "interview_scripts_v1.json").write_text(json.dumps(scripts))

    from api.database import get_connection
    tokens = [f"peak-token-{i:02d}" for i in range(20)]
    async with get_connection(slug) as conn:
        await conn.execute("INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
        cur = await conn.execute("SELECT id FROM projects WHERE slug=?", (slug,))
        pid = (await cur.fetchone())[0]
        # agent_outputs has no run_id column. The brief's own snippet included one - checked
        # against the live schema in api/database.py rather than trusted, per the warning
        # that an earlier task's brief got exactly this wrong.
        await conn.execute(
            "INSERT INTO agent_outputs (project_id, agent_name, output_type, "
            "version, is_current, file_path) VALUES (?,?,?,?,?,?)",
            (pid, "interaction_designer", "interview_scripts", 1, 1,
             str(outputs / "interview_scripts_v1.json")),
        )
        await conn.commit()
        # interview_sessions.stakeholder_id carries an enforced foreign key (PRAGMA
        # foreign_keys = ON in get_connection), so every session needs a stakeholder behind
        # it - the brief's snippet used bare integers 1..20 and would fail on insert.
        for i in range(len(tokens)):
            await conn.execute(
                "INSERT INTO stakeholders (project_id, name) VALUES (?,?)",
                (pid, f"Stakeholder {i + 1}"),
            )
        await conn.commit()
        cur = await conn.execute(
            "SELECT id FROM stakeholders WHERE project_id=? ORDER BY id", (pid,)
        )
        stakeholder_ids = [row[0] for row in await cur.fetchall()]
        for token, sid in zip(tokens, stakeholder_ids):
            await conn.execute(
                "INSERT INTO interview_sessions (project_id, stakeholder_id, node_label, "
                "session_token, status) VALUES (?,?,?,?,?)",
                (pid, sid, "Frontline Interview", token, "pending"),
            )
        await conn.commit()
    yield Campaign(slug=slug, tokens=tokens)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_twenty_sessions_complete_concurrently(client, seeded_campaign):
    """Twenty simultaneous completions - the end of a lunch break.

    Asserts three things at once: every completion succeeds, no session sees a locked
    database, and each session's answers are its own. seeded_campaign creates one project
    with 20 sessions and a current interview_scripts artefact.

    What this proves and what it does not - checked by hand, not assumed:

    asyncio.gather over one ASGITransport client drives twenty requests through the same
    event loop, so the FastAPI routing, Pydantic validation and endpoint bodies genuinely
    interleave rather than run one after another. aiosqlite.Connection is a real Thread
    subclass, so each of the twenty requests that reaches the database does so from its own
    OS thread, not a simulation of one. That much is real concurrency, not just interleaving.

    What it does NOT prove: that SQLite write contention is reached. It is not, on this
    workload. A companion probe (not part of this suite, run by hand outside pytest)
    confirmed that a bare threading.Barrier around raw sqlite3 connections - no aiosqlite,
    no asyncio - reproduces "database is locked" reliably at busy_timeout=0 (1-2/20 succeed)
    and clears it at busy_timeout=10000 (20/20), so the mechanism this repo relies on is
    real. But driving the same twenty writes through this test's actual path - the real
    HTTP request, the real event loop, real aiosqlite worker threads - never reproduced a
    lock, even at 500 concurrent sessions, and even with a threading.Barrier spliced into
    aiosqlite's own worker-thread execute call to force the twenty INSERTs to fire in the
    same instant. The GIL and aiosqlite's one-job-at-a-time-per-connection dispatch appear
    to keep actual SQLite writes from ever truly colliding at this transaction size, on this
    machine. So this test's "no session sees a locked database" assertion is a live check,
    not a decorative one - but on the evidence gathered, nothing plausible in this codebase
    would make it fail here; the WAL/busy_timeout guarantee is exercised and proven
    separately, not by this test.

    A second, unrelated finding from the same investigation, worth a reviewer's attention:
    the endpoint's actual write path - complete_session and _find_session_db in
    api/services/interview_service.py - opens its connections with a bare
    aiosqlite.connect(db_path), not api.database.get_connection(slug). WAL survives that
    regardless, because it is a persistent property of the database file once any code path
    sets it (this fixture's own get_connection calls do). busy_timeout does not survive it -
    it is per-connection, and nothing sets it on this path. It happens not to matter for
    this workload, per the probe above, but the CLAUDE.md guarantee ("get_connection sets
    ... busy_timeout=10000") does not actually reach the /complete endpoint's writes. Out of
    scope here (this task touches only this test file); flagged for a follow-up task.

    It does not prove behaviour under multi-process load or real network concurrency, which
    this repository has no harness for.
    """
    import asyncio
    pairs = [{"question_id": "q1", "question": "Q?", "answer": "A"}]

    async def complete(token):
        return await client.patch(f"/api/interviews/{token}/complete",
                                  json={"qa_pairs": pairs})

    results = await asyncio.gather(*[complete(t) for t in seeded_campaign.tokens])
    statuses = [r.status_code for r in results]
    assert all(s == 200 for s in statuses), f"not every completion succeeded: {statuses}"

    from api.database import get_connection
    async with get_connection(seeded_campaign.slug) as conn:
        cur = await conn.execute(
            "SELECT session_id, COUNT(*) FROM interview_answers GROUP BY session_id")
        counts = dict(await cur.fetchall())
    assert len(counts) == 20, "not every session recorded its answers"
    assert set(counts.values()) == {1}, f"answers leaked between sessions: {counts}"
