# tests/test_approval_commits.py
"""Commits freeze output versions; changes record what was asked of an output.

A commit is the only act that is not a change - it fixes a version and releases it,
and later projects diff consecutive commits to find what moved.
"""
import pytest
from pathlib import Path

from api.config import get_settings

SLUG = "commit-test"
PROJECT = {
    "client_slug": SLUG,
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
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


async def _make_output(agent_name: str = "value_chain_mapper") -> int:
    from api.database import get_connection, fetch_project, insert_agent_output
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        return await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name=agent_name,
            output_type="value_chain",
            file_path="/tmp/vc.json",
            version=1,
        )


@pytest.mark.asyncio
async def test_a_commit_records_who_and_freezes_the_outputs_it_names(client):
    await client.post("/projects", json=PROJECT)
    output_id = await _make_output("commit-test")

    from api.database import (
        get_connection, insert_approval_commit, link_commit_outputs,
        fetch_approval_commits,
    )
    async with get_connection(SLUG) as conn:
        commit_id = await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="admin", notes="looks right"
        )
        await link_commit_outputs(conn, commit_id=commit_id, output_ids=[output_id])
        commits = await fetch_approval_commits(conn)

    assert len(commits) == 1
    assert commits[0]["crew_name"] == "discovery_mapping"
    assert commits[0]["committed_by"] == "admin"
    assert commits[0]["notes"] == "looks right"


@pytest.mark.asyncio
async def test_crew_has_commit_distinguishes_committed_crews(client):
    await client.post("/projects", json=PROJECT)

    from api.database import get_connection, insert_approval_commit, crew_has_commit
    async with get_connection(SLUG) as conn:
        assert await crew_has_commit(conn, crew_name="discovery_mapping") is False
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="admin"
        )
        assert await crew_has_commit(conn, crew_name="discovery_mapping") is True
        # Committing one crew says nothing about another.
        assert await crew_has_commit(conn, crew_name="assessment_design") is False


@pytest.mark.asyncio
async def test_crew_is_running_distinguishes_by_crew_and_status(client):
    await client.post("/projects", json=PROJECT)

    from api.database import (
        crew_is_running, get_connection, insert_crew_run, fetch_project,
        update_crew_run_status,
    )
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        assert await crew_is_running(conn, crew_name="discovery_mapping") is False

        run_id = await insert_crew_run(
            conn, project_id=project["id"], crew_name="discovery_mapping", status="running"
        )
        assert await crew_is_running(conn, crew_name="discovery_mapping") is True
        # A different crew running says nothing about this one.
        assert await crew_is_running(conn, crew_name="assessment_design") is False

        await update_crew_run_status(conn, run_id=run_id, status="completed")
        assert await crew_is_running(conn, crew_name="discovery_mapping") is False


@pytest.mark.asyncio
async def test_latest_commit_at_is_none_until_a_commit_exists(client):
    await client.post("/projects", json=PROJECT)

    from api.database import get_connection, insert_approval_commit, latest_commit_at
    async with get_connection(SLUG) as conn:
        assert await latest_commit_at(conn, crew_name="discovery_mapping") is None
        await insert_approval_commit(
            conn, crew_name="discovery_mapping", committed_by="admin"
        )
        assert await latest_commit_at(conn, crew_name="discovery_mapping") is not None
        # A different crew's commit says nothing about this one.
        assert await latest_commit_at(conn, crew_name="assessment_design") is None


@pytest.mark.asyncio
async def test_a_crew_with_no_outputs_can_still_be_committed(client):
    """Some crews produce no artefact, and readiness asks only whether a commit exists."""
    await client.post("/projects", json=PROJECT)

    from api.database import get_connection, insert_approval_commit, link_commit_outputs, crew_has_commit
    async with get_connection(SLUG) as conn:
        commit_id = await insert_approval_commit(
            conn, crew_name="stakeholder_management", committed_by="admin"
        )
        await link_commit_outputs(conn, commit_id=commit_id, output_ids=[])
        assert await crew_has_commit(conn, crew_name="stakeholder_management") is True


@pytest.mark.asyncio
async def test_changes_record_who_asked_and_what_the_agent_did(client):
    await client.post("/projects", json=PROJECT)
    output_id = await _make_output("commit-test")

    from api.database import get_connection, insert_output_change, fetch_output_changes
    async with get_connection(SLUG) as conn:
        await insert_output_change(
            conn,
            output_id=output_id,
            requested_by="patrick",
            source="note",
            request="Add an L3 for asset tagging",
            summary="",
        )
        changes = await fetch_output_changes(conn, output_ids=[output_id])

    assert len(changes) == 1
    assert changes[0]["requested_by"] == "patrick"
    assert changes[0]["source"] == "note"
    assert changes[0]["request"] == "Add an L3 for asset tagging"


@pytest.mark.asyncio
async def test_fetching_changes_for_no_outputs_returns_nothing_rather_than_everything(client):
    """An empty id list must not degenerate into an unfiltered query."""
    await client.post("/projects", json=PROJECT)
    output_id = await _make_output("commit-test")

    from api.database import get_connection, insert_output_change, fetch_output_changes
    async with get_connection(SLUG) as conn:
        await insert_output_change(
            conn, output_id=output_id, requested_by="p", source="note", request="x"
        )
        assert await fetch_output_changes(conn, output_ids=[]) == []
