# tests/test_autostart_service.py
"""Auto-start turns an approval into the next crew running.

dispatch_crew is patched throughout: these tests are about which crews are started and
what is reported, not about running CrewAI. Assertions are on the returned report and on
the crew_runs rows, both of which are deterministic - asserting on the patched
coroutine having been awaited is not, because asyncio.create_task does not guarantee the
task has run before the test ends.
"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from api.config import get_settings
from api.database import (
    fetch_approval_commits,
    fetch_crew_runs,
    fetch_project,
    get_connection,
    insert_approval_commit,
    insert_crew_run,
    set_project_status,
)
from api.services.autostart_service import start_ready_downstream
from api.services.run_service import dispatch_crew

SLUG = "autostart-test"
PROJECT = {
    "client_slug": "autostart-test",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.fixture(autouse=True)
def clean():
    # Each test runs against the same slug, and the readiness/started assertions
    # depend on that project starting with no prior commits or runs - so the db is
    # wiped before and after every test, mirroring tests/test_commit_endpoint.py.
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


async def _activate(slug: str) -> None:
    async with get_connection(slug) as conn:
        await set_project_status(conn, slug=slug, status="active")


@pytest.mark.asyncio
async def test_a_ready_crew_is_started_and_reported_with_its_run_id(client):
    await client.post("/projects", json=PROJECT)
    await _activate(SLUG)
    async with get_connection(SLUG) as conn:
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="a", notes=""
        )

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        result = await start_ready_downstream(
            SLUG, "discovery_mapping", committed_by="approver@example.com"
        )

    started = {s["crew"]: s["run_id"] for s in result["started"]}
    assert "assessment_design" in started
    assert isinstance(started["assessment_design"], int)


@pytest.mark.asyncio
async def test_starting_a_crew_records_a_running_crew_run(client):
    await client.post("/projects", json=PROJECT)
    await _activate(SLUG)
    async with get_connection(SLUG) as conn:
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="a", notes=""
        )

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        await start_ready_downstream(SLUG, "discovery_mapping", committed_by="a")

    async with get_connection(SLUG) as conn:
        project_row = await fetch_project(conn, slug=SLUG)
        runs = await fetch_crew_runs(conn, project_id=project_row["id"])
    assert any(
        r["crew_name"] == "assessment_design" and r["status"] == "running" for r in runs
    )


@pytest.mark.asyncio
async def test_a_crew_with_an_uncommitted_upstream_is_waiting_not_started(client):
    """discovery_interviews needs both assessment_design and stakeholder_management."""
    await client.post("/projects", json=PROJECT)
    await _activate(SLUG)
    async with get_connection(SLUG) as conn:
        await insert_approval_commit(
            conn, crew_name="assessment_design", committed_by="a", notes=""
        )

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        result = await start_ready_downstream(SLUG, "assessment_design", committed_by="a")

    waiting = {w["crew"]: w["waiting_on"] for w in result["waiting"]}
    assert waiting["discovery_interviews"] == ["stakeholder_management"]
    assert not any(s["crew"] == "discovery_interviews" for s in result["started"])


@pytest.mark.asyncio
async def test_a_running_crew_is_skipped_and_named(client):
    await client.post("/projects", json=PROJECT)
    await _activate(SLUG)
    async with get_connection(SLUG) as conn:
        project_row = await fetch_project(conn, slug=SLUG)
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="a", notes=""
        )
        await insert_crew_run(
            conn,
            project_id=project_row["id"],
            crew_name="assessment_design",
            status="running",
        )

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        result = await start_ready_downstream(SLUG, "discovery_mapping", committed_by="a")

    assert result["skipped"] == ["assessment_design"]
    assert result["started"] == []


@pytest.mark.asyncio
async def test_an_inactive_project_starts_nothing_and_says_why(client):
    """Every project in this codebase is 'created' until an approver activates it, so this
    is the state auto-start meets first. The ready crew must NOT be reported as waiting -
    it is not waiting on an upstream."""
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="a", notes=""
        )

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        result = await start_ready_downstream(SLUG, "discovery_mapping", committed_by="a")

    assert result == {"started": [], "skipped": [], "waiting": [], "inactive": True}


@pytest.mark.asyncio
async def test_an_inactive_project_records_no_crew_run(client):
    await client.post("/projects", json=PROJECT)
    async with get_connection(SLUG) as conn:
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="a", notes=""
        )

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        await start_ready_downstream(SLUG, "discovery_mapping", committed_by="a")

    async with get_connection(SLUG) as conn:
        project_row = await fetch_project(conn, slug=SLUG)
        runs = await fetch_crew_runs(conn, project_id=project_row["id"])
    assert runs == []


@pytest.mark.asyncio
async def test_an_active_project_reports_inactive_false(client):
    await client.post("/projects", json=PROJECT)
    await _activate(SLUG)
    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        result = await start_ready_downstream(SLUG, "business_plan", committed_by="a")

    assert result["inactive"] is False


@pytest.mark.asyncio
async def test_a_crew_finishing_starts_nothing_further(client):
    """Cascade safety, exercised at its actual source.

    This is a property of dispatch_crew's success path, not of start_ready_downstream:
    a crew completing must not commit anything or start anything, which is why one
    approval can start at most the crews directly below it and never chains onwards
    on its own. An earlier version of this test drove the completion by issuing a raw
    UPDATE against crew_runs and then asserting nothing had started - but nothing in
    the codebase listens for a crew_runs status change, so that assertion held for any
    implementation, including a broken one; it proved only that SQL does not invoke
    Python.

    This version calls dispatch_crew directly (the entry point asyncio.create_task
    actually schedules) and lets it run its real success path, with only
    build_and_run_crew (no CrewAI) and the awaiting-commit notification (no email)
    replaced. If dispatch_crew's completion path ever grew an auto-commit or an
    auto-start, this would catch it: either a new approval_commits row would appear,
    or a new crew_runs row for stakeholder_management would - stakeholder_management
    being what a commit to assessment_design would release.
    """
    await client.post("/projects", json=PROJECT)
    await _activate(SLUG)
    async with get_connection(SLUG) as conn:
        project_row = await fetch_project(conn, slug=SLUG)
        run_id = await insert_crew_run(
            conn,
            project_id=project_row["id"],
            crew_name="assessment_design",
            status="running",
        )

    with patch(
        "api.services.run_service.build_and_run_crew", AsyncMock(return_value="ok")
    ), patch(
        "api.services.commit_notify_service.notify_crew_awaiting_commit", AsyncMock()
    ):
        await dispatch_crew(slug=SLUG, crew_name="assessment_design", run_id=run_id)

    async with get_connection(SLUG) as conn:
        project_row = await fetch_project(conn, slug=SLUG)
        runs = await fetch_crew_runs(conn, project_id=project_row["id"])
        commits = await fetch_approval_commits(conn)

    assert commits == []
    assert [r["crew_name"] for r in runs] == ["assessment_design"]
    assert not any(r["crew_name"] == "stakeholder_management" for r in runs)
