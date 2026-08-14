import pytest
import pytest_asyncio
from api.database import get_connection
from api.services.script_review_service import record_script_review


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    from api.config import get_settings
    get_settings.cache_clear()
    async with get_connection("rev-test") as conn:
        await conn.execute("INSERT INTO projects (slug) VALUES ('rev-test')")
        await conn.execute(
            "INSERT INTO interview_script_ledger (script_id, project_id, node_id, last_version)"
            " VALUES ('SC-001', 1, '1.2', 5)")
        await conn.commit()
        yield conn
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_review_stamps_the_version_that_was_read(project):
    """A tick is a statement about content, not about an id. Recording which version was
    read is what lets a later change show the tick as stale instead of silently wrong."""
    row = await record_script_review(project, project_id=1, script_id="SC-001",
                                     reviewer="ana", decision="reviewed", at_version=5)
    assert row["review_status"] == "reviewed"
    assert row["reviewed_at_version"] == 5


@pytest.mark.asyncio
async def test_a_script_can_be_reviewed_by_several_people(project):
    await record_script_review(project, project_id=1, script_id="SC-001",
                               reviewer="ana", decision="reviewed", at_version=5)
    await record_script_review(project, project_id=1, script_id="SC-001",
                               reviewer="bo", decision="reviewed", at_version=5)
    cur = await project.execute("SELECT reviewer FROM script_reviews ORDER BY id")
    assert [r[0] for r in await cur.fetchall()] == ["ana", "bo"]


@pytest.mark.asyncio
async def test_a_script_is_approved_only_once(project):
    """AlreadyApprovedError is a ValueError subclass, so this refusal is still catchable
    by any existing caller that only knows about ValueError - see
    api.services.script_review_service.AlreadyApprovedError for why the router needs the
    narrower type rather than pattern-matching this message."""
    from api.services.script_review_service import AlreadyApprovedError
    # A read satisfies the separate not-yet-reviewed gate (see test_approve_gate.py) so
    # the approval below succeeds for the reason this test is actually about.
    await record_script_review(project, project_id=1, script_id="SC-001",
                               reviewer="ana", decision="reviewed", at_version=5)
    await record_script_review(project, project_id=1, script_id="SC-001",
                               reviewer="ana", decision="approved", at_version=5)
    # Asserted on type, not on message wording - callers (the router included) branch
    # on AlreadyApprovedError, not on what the message happens to say.
    with pytest.raises(AlreadyApprovedError):
        await record_script_review(project, project_id=1, script_id="SC-001",
                                   reviewer="bo", decision="approved", at_version=5)


@pytest.mark.asyncio
async def test_a_send_back_clears_approval_and_records_its_target(project):
    # A read satisfies the separate not-yet-reviewed gate (see test_approve_gate.py) so
    # the approval below succeeds for the reason this test is actually about.
    await record_script_review(project, project_id=1, script_id="SC-001",
                               reviewer="ana", decision="reviewed", at_version=5)
    await record_script_review(project, project_id=1, script_id="SC-001",
                               reviewer="ana", decision="approved", at_version=5)
    row = await record_script_review(project, project_id=1, script_id="SC-001",
                                     reviewer="bo", decision="changes_requested",
                                     notes="the maturity anchors are wrong",
                                     at_version=5, return_to="agent")
    assert row["review_status"] == "changes_requested"
    assert row["review_return_to"] == "agent"


@pytest.mark.asyncio
async def test_a_send_back_must_say_where_it_is_going(project):
    """A send-back with no target would default to something, and either default is wrong:
    to the agent it rewrites an instrument a reviewer is about to re-read, to the reviewer
    it silently drops a request for regeneration."""
    with pytest.raises(ValueError, match="return_to"):
        await record_script_review(project, project_id=1, script_id="SC-001",
                                   reviewer="bo", decision="changes_requested", at_version=5)


@pytest.mark.asyncio
async def test_a_regenerated_script_no_longer_awaits_regeneration(project):
    """A send-back must clear on evidence the work was done, not on the assumption that a
    kickoff meant it was - the run that regenerates a script may die before reaching any
    close-out call, and a close-out would then discard a request that was never actually
    fulfilled just as wrongly as never clearing would repeat one that was. last_version
    advancing past reviewed_at_version is register_scripts_sync's own signal that a later
    batch named this script_id again; scripts_awaiting_regeneration reads that signal
    directly rather than relying on a caller to mark the row done."""
    from api.services.script_review_service import scripts_awaiting_regeneration
    await record_script_review(project, project_id=1, script_id="SC-001", reviewer="bo",
                               decision="changes_requested", notes="regenerate this",
                               at_version=5, return_to="agent")
    pending = await scripts_awaiting_regeneration(project, project_id=1)
    assert [p["script_id"] for p in pending] == ["SC-001"]

    # register_scripts_sync's own effect on a batch that names this script_id again.
    await project.execute(
        "UPDATE interview_script_ledger SET last_version=6 WHERE script_id='SC-001'")
    await project.commit()

    pending = await scripts_awaiting_regeneration(project, project_id=1)
    assert pending == [], "last_version has moved past reviewed_at_version - the note was addressed"


@pytest.mark.asyncio
async def test_only_a_send_back_to_the_agent_awaits_regeneration(project):
    """The load-bearing distinction. A return to reviewers must never reach Maya, or
    'please look at this again' rewrites the instrument out from under the reviewer."""
    from api.services.script_review_service import scripts_awaiting_regeneration
    await project.execute(
        "INSERT INTO interview_script_ledger (script_id, project_id, node_id) "
        "VALUES ('SC-002', 1, '1.3')")
    await project.commit()
    await record_script_review(project, project_id=1, script_id="SC-001", reviewer="bo",
                               decision="changes_requested", notes="regenerate this",
                               at_version=5, return_to="agent")
    await record_script_review(project, project_id=1, script_id="SC-002", reviewer="bo",
                               decision="changes_requested", notes="please re-read",
                               at_version=5, return_to="reviewer")
    pending = await scripts_awaiting_regeneration(project, project_id=1)
    assert [p["script_id"] for p in pending] == ["SC-001"]
    assert pending[0]["notes"] == "regenerate this"
