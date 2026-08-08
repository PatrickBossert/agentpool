# tests/test_interview_answers.py
"""One row per question per session, tagged at the moment it was answered."""
import asyncio
import shutil
import time
from pathlib import Path

import pytest
import pytest_asyncio

from api.config import get_settings
from api.database import fetch_interview_answers, get_connection
from api.services import interview_answer_service as svc
from api.services.interview_answer_service import record_answers

SLUG = "answers-test"
PROJECT = {
    "client_slug": SLUG, "llm_mode": "standard", "sector": "utilities",
    "stakeholder_groups": [], "value_stream_labels": [], "crews_enabled": ["requirements"],
    "review_gates": True, "slack_channel": "",
}
SCRIPT = {
    "script_id": "SC-014", "node_id": "1.2", "level": "L2", "relationship": "internal",
    "node_label": "Planned Maintenance", "sections": [{
        "section_id": "S3", "title": "Data", "discipline": "data",
        "question_intent": "evidence", "elicitation": "unprompted",
        "questions": [{"id": "Q1", "text": "Is the record trusted?"},
                      {"id": "Q2", "text": "For investment?", "discipline": "governance"}],
    }],
}
PAIRS = [
    {"question_id": "SC-014.S3.Q1", "question": "Is the record trusted?",
     "answer": "For compliance, yes.", "follow_up": 0},
    {"question_id": "SC-014.S3.Q1.F1", "question": "Say more?",
     "answer": "Not for planning.", "follow_up": 1},
    {"question_id": "SC-014.S3.Q2", "question": "For investment?",
     "answer": "", "follow_up": 0},
]


@pytest.fixture(autouse=True)
def clean():
    """A fresh database per test.

    interview_sessions.session_token is UNIQUE, so a database surviving between tests makes
    the second seed fail on a constraint rather than on anything under test.
    """
    def wipe():
        settings = get_settings()
        Path(settings.database_dir, f"{SLUG}.db").unlink(missing_ok=True)
        project_dir = Path(settings.projects_dir, SLUG)
        if project_dir.exists():
            shutil.rmtree(project_dir)
    wipe()
    yield
    get_settings.cache_clear()
    wipe()


@pytest_asyncio.fixture
async def seeded_session(client):
    """A project, a stakeholder, and one session - the minimum an answer row references."""
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall("SELECT id FROM projects LIMIT 1")
        project_id = rows[0][0]
        cur = await conn.execute(
            "INSERT INTO stakeholders (project_id, name, email, job_title) VALUES (?,?,?,?)",
            (project_id, "Sam Example", "sam@example.com", "Manager"),
        )
        stakeholder_id = cur.lastrowid
        cur = await conn.execute(
            "INSERT INTO interview_sessions (project_id, stakeholder_id, node_label, "
            "session_token, status) VALUES (?,?,?,?,?)",
            (project_id, stakeholder_id, "Planned Maintenance", "tok-answers", "completed"),
        )
        await conn.commit()
        return cur.lastrowid


@pytest.mark.asyncio
async def test_every_pair_becomes_a_row(seeded_session):
    async with get_connection(SLUG) as conn:
        written = await record_answers(conn, SLUG, seeded_session, PAIRS, script=SCRIPT)
        rows = await fetch_interview_answers(conn, session_id=seeded_session)
    assert written == 3
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_the_tags_come_from_the_script_not_from_the_answer(seeded_session):
    async with get_connection(SLUG) as conn:
        await record_answers(conn, SLUG, seeded_session, PAIRS, script=SCRIPT)
        rows = await fetch_interview_answers(conn, session_id=seeded_session)
    by_qid = {r["question_id"]: r for r in rows}
    assert by_qid["SC-014.S3.Q1"]["discipline"] == "data"
    assert by_qid["SC-014.S3.Q1"]["node_id"] == "1.2"
    assert by_qid["SC-014.S3.Q1"]["relationship"] == "internal"


@pytest.mark.asyncio
async def test_a_question_override_wins_over_its_section(seeded_session):
    async with get_connection(SLUG) as conn:
        await record_answers(conn, SLUG, seeded_session, PAIRS, script=SCRIPT)
        rows = await fetch_interview_answers(conn, session_id=seeded_session)
    q2 = next(r for r in rows if r["question_id"] == "SC-014.S3.Q2")
    assert q2["discipline"] == "governance"


@pytest.mark.asyncio
async def test_a_follow_up_carries_its_parents_tags_and_is_flagged(seeded_session):
    """A probe is more evidence about one question. Its own tags would let a generated
    follow-up land in a discipline nobody chose."""
    async with get_connection(SLUG) as conn:
        await record_answers(conn, SLUG, seeded_session, PAIRS, script=SCRIPT)
        rows = await fetch_interview_answers(conn, session_id=seeded_session)
    probe = next(r for r in rows if r["question_id"] == "SC-014.S3.Q1.F1")
    assert probe["follow_up"] == 1
    assert probe["discipline"] == "data"


@pytest.mark.asyncio
async def test_a_probe_takes_its_parents_override_not_the_sections_tag(seeded_session):
    """The discriminating case, and the fixture above cannot be it.

    A probe on Q1 resolves to section S3 whether or not the parent is resolved, because Q1
    has no override - so both behaviours give `data` and the test passes either way. Q2
    overrides to `governance`, so a probe on Q2 lands in the wrong discipline the moment the
    parent stops being resolved.
    """
    pairs = [{"question_id": "SC-014.S3.Q2.F1", "question": "Say more?",
              "answer": "Not reliable.", "follow_up": 1}]
    async with get_connection(SLUG) as conn:
        await record_answers(conn, SLUG, seeded_session, pairs, script=SCRIPT)
        rows = await fetch_interview_answers(conn, session_id=seeded_session)
    assert rows[0]["discipline"] == "governance"


@pytest.mark.asyncio
async def test_a_probe_does_not_count_as_a_question_covered(seeded_session):
    """One question and one probe is one question covered, not two - otherwise pressing an
    interviewee inflates coverage."""
    async with get_connection(SLUG) as conn:
        await record_answers(conn, SLUG, seeded_session, PAIRS, script=SCRIPT)
        rows = await fetch_interview_answers(conn, session_id=seeded_session)
    assert len([r for r in rows if not r["follow_up"]]) == 2


@pytest.mark.asyncio
async def test_an_unanswered_question_is_recorded_as_asked(seeded_session):
    """An absent row means "not asked" and a blank one means "asked and not answered".
    Coverage cannot tell an instrument that missed a topic from a stakeholder who declined
    it unless both are recorded."""
    async with get_connection(SLUG) as conn:
        await record_answers(conn, SLUG, seeded_session, PAIRS, script=SCRIPT)
        rows = await fetch_interview_answers(conn, session_id=seeded_session)
    blank = next(r for r in rows if r["question_id"] == "SC-014.S3.Q2")
    assert blank["answered"] == 0
    assert blank["answer_text"] == ""


@pytest.mark.asyncio
async def test_an_entity_anchored_script_has_no_chain(seeded_session):
    """A query for everything about Fleet that swept in entity-level answers would attribute
    a board member's remark to a chain they never mentioned."""
    entity_script = {**SCRIPT, "node_id": "0", "level": "A", "relationship": "regulator"}
    async with get_connection(SLUG) as conn:
        await record_answers(conn, SLUG, seeded_session, PAIRS[:1], script=entity_script)
        rows = await fetch_interview_answers(conn, session_id=seeded_session)
    assert rows[0]["chain"] is None
    assert rows[0]["relationship"] == "regulator"


@pytest.mark.asyncio
async def test_a_chain_anchored_script_records_its_chain(seeded_session):
    async with get_connection(SLUG) as conn:
        await record_answers(conn, SLUG, seeded_session, PAIRS[:1], script=SCRIPT)
        rows = await fetch_interview_answers(conn, session_id=seeded_session)
    assert rows[0]["chain"] == "1"


@pytest.mark.asyncio
async def test_a_synthesis_prompt_belongs_to_no_section_and_still_records(seeded_session):
    """The synthesis block sits after every section. Dropping those answers because they
    resolve to no section would lose the wrap-up, which is where an interviewee names the
    single most important thing."""
    pairs = [{"question_id": "SC-014.SYNTH.Q1", "question": "Anything missed?",
              "answer": "The asset register.", "follow_up": 0}]
    async with get_connection(SLUG) as conn:
        written = await record_answers(conn, SLUG, seeded_session, pairs, script=SCRIPT)
        rows = await fetch_interview_answers(conn, session_id=seeded_session)
    assert written == 1
    assert rows[0]["node_id"] == "1.2"


@pytest.mark.asyncio
async def test_indexing_does_not_delay_a_concurrent_session(seeded_session, monkeypatch):
    """The event-loop property, exercised through record_answers itself.

    tests/test_interview_concurrency.py proves _index_in_background frees the loop, but it
    calls that helper directly - it would keep passing even if record_answers' call site
    reverted to the original synchronous `index_answers(slug, [...])` and left the helper
    unused. Only a test that drives record_answers, the call site the brief names as the
    actual defect, can catch that regression. index_answers is stubbed with a blocking sleep
    standing in for a slow or unreachable Chroma.
    """
    def slow_index(slug, rows):
        time.sleep(0.5)
        return len(rows)

    monkeypatch.setattr(svc, "index_answers", slow_index)

    async def waiter(t0):
        await asyncio.sleep(0.01)
        return time.perf_counter() - t0

    async with get_connection(SLUG) as conn:
        t0 = time.perf_counter()
        written, waited = await asyncio.gather(
            record_answers(conn, SLUG, seeded_session, PAIRS, script=SCRIPT),
            waiter(t0),
        )
    assert written == 3
    assert waited < 0.2, (
        f"a concurrent session waited {waited:.2f}s while another completed - "
        "indexing is still on the event loop"
    )
