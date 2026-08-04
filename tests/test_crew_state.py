# tests/test_crew_state.py
"""Three states, derived rather than stored.

The contributor shapes the output and says when it is ready; only then is the approver
summoned. Two states could not express the gap between those two acts.
"""
import shutil
from pathlib import Path

import pytest

from api.config import get_settings

SLUG = "state-test"
PROJECT = {
    "client_slug": SLUG,
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["requirements"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.fixture(autouse=True)
def clean():
    """Unlink before and after - these tests share one slug."""
    def wipe():
        settings = get_settings()
        Path(settings.database_dir, f"{SLUG}.db").unlink(missing_ok=True)
        proj = Path(settings.projects_dir, SLUG)
        if proj.exists():
            shutil.rmtree(proj)
    wipe()
    yield
    get_settings.cache_clear()
    wipe()


@pytest.mark.asyncio
async def test_a_crew_nobody_has_touched_is_working(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection
    from api.services.crew_state_service import crew_state
    async with get_connection(SLUG) as conn:
        assert await crew_state(conn, crew_name="discovery_mapping") == "working"


@pytest.mark.asyncio
async def test_a_submission_makes_it_ready(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, insert_crew_submission
    from api.services.crew_state_service import crew_state
    async with get_connection(SLUG) as conn:
        await insert_crew_submission(
            conn, crew_name="discovery_mapping", submitted_by="alice"
        )
        assert await crew_state(conn, crew_name="discovery_mapping") == "ready"


@pytest.mark.asyncio
async def test_a_commit_after_a_submission_makes_it_committed(client):
    await client.post("/projects", json=PROJECT)
    from api.database import (
        get_connection, insert_crew_submission, insert_approval_commit,
    )
    from api.services.crew_state_service import crew_state
    async with get_connection(SLUG) as conn:
        await insert_crew_submission(
            conn, crew_name="discovery_mapping", submitted_by="alice",
        )
        await conn.execute(
            "UPDATE crew_submissions SET submitted_at='2026-01-01 09:00:00'"
        )
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="bob"
        )
        await conn.execute(
            "UPDATE approval_commits SET committed_at='2026-01-01 10:00:00'"
        )
        await conn.commit()
        assert await crew_state(conn, crew_name="discovery_mapping") == "committed"


@pytest.mark.asyncio
async def test_a_commit_alone_is_committed(client):
    """A crew committed without ever being submitted - the SP20a path."""
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, insert_approval_commit
    from api.services.crew_state_service import crew_state
    async with get_connection(SLUG) as conn:
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="bob"
        )
        assert await crew_state(conn, crew_name="discovery_mapping") == "committed"


@pytest.mark.asyncio
async def test_resubmitting_after_approval_returns_it_to_ready(client):
    """The ordinary case once a crew has been round the loop once."""
    await client.post("/projects", json=PROJECT)
    from api.database import (
        get_connection, insert_crew_submission, insert_approval_commit,
    )
    from api.services.crew_state_service import crew_state
    async with get_connection(SLUG) as conn:
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="bob"
        )
        await conn.execute(
            "UPDATE approval_commits SET committed_at='2026-01-01 10:00:00'"
        )
        await insert_crew_submission(
            conn, crew_name="discovery_mapping", submitted_by="alice"
        )
        await conn.execute(
            "UPDATE crew_submissions SET submitted_at='2026-01-02 09:00:00'"
        )
        await conn.commit()
        assert await crew_state(conn, crew_name="discovery_mapping") == "ready"


@pytest.mark.asyncio
async def test_a_tie_resolves_to_committed(client):
    """The approver's act wins, so a crew cannot be stuck in ready after approval."""
    await client.post("/projects", json=PROJECT)
    from api.database import (
        get_connection, insert_crew_submission, insert_approval_commit,
    )
    from api.services.crew_state_service import crew_state
    async with get_connection(SLUG) as conn:
        await insert_crew_submission(
            conn, crew_name="discovery_mapping", submitted_by="alice"
        )
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="bob"
        )
        await conn.execute(
            "UPDATE crew_submissions SET submitted_at='2026-01-01 10:00:00'"
        )
        await conn.execute(
            "UPDATE approval_commits SET committed_at='2026-01-01 10:00:00'"
        )
        await conn.commit()
        assert await crew_state(conn, crew_name="discovery_mapping") == "committed"


@pytest.mark.asyncio
async def test_state_of_one_crew_says_nothing_about_another(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, insert_crew_submission
    from api.services.crew_state_service import crew_state, crew_state_report
    async with get_connection(SLUG) as conn:
        await insert_crew_submission(
            conn, crew_name="discovery_mapping", submitted_by="alice"
        )
        assert await crew_state(conn, crew_name="assessment_design") == "working"
        report = await crew_state_report(conn)
    assert report["discovery_mapping"] == "ready"
    assert report["assessment_design"] == "working"
