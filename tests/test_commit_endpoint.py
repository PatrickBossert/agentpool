# tests/test_commit_endpoint.py
"""Committing a crew's outputs, and who is allowed to.

The identity model cannot yet express "only approvers commit": the users table is
empty and every login is sysadmin. The rule is written so it is correct now and
tightens by itself once per-user accounts exist.
"""
from pathlib import Path

import pytest

from api.config import get_settings

SLUG = "commit-api-test"
PROJECT = {
    "client_slug": "commit-api-test",
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
    # Each test commits against the same slug, and readiness/"released" assertions
    # depend on that project starting with no prior commits - so the db is wiped
    # before and after every test, mirroring tests/test_approval_commits.py.
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


async def _make_output(slug: str, agent_name: str) -> int:
    from api.database import get_connection, fetch_project, insert_agent_output
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        return await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name=agent_name,
            output_type="value_chain",
            file_path="/tmp/vc.json",
            version=1,
        )


@pytest.mark.asyncio
async def test_committing_freezes_only_that_crews_outputs(client):
    await client.post("/projects", json=PROJECT)
    mine = await _make_output("commit-api-test", "value_chain_mapper")   # discovery_mapping
    theirs = await _make_output("commit-api-test", "interaction_designer")  # assessment_design

    resp = await client.post(
        "/projects/commit-api-test/commits",
        json={"crew_name": "discovery_mapping", "notes": "signed off"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["output_ids"] == [mine]
    assert theirs not in body["output_ids"]


@pytest.mark.asyncio
async def test_committing_reports_the_crews_it_released(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.post(
        "/projects/commit-api-test/commits",
        json={"crew_name": "discovery_mapping", "notes": ""},
    )
    assert resp.json()["released"] == ["assessment_design"]


@pytest.mark.asyncio
async def test_a_crew_released_only_when_its_last_upstream_lands(client):
    """discovery_interviews needs both assessment_design and stakeholder_management."""
    await client.post("/projects", json=PROJECT)
    first = await client.post(
        "/projects/commit-api-test/commits",
        json={"crew_name": "assessment_design", "notes": ""},
    )
    assert "discovery_interviews" not in first.json()["released"]

    second = await client.post(
        "/projects/commit-api-test/commits",
        json={"crew_name": "stakeholder_management", "notes": ""},
    )
    assert "discovery_interviews" in second.json()["released"]


@pytest.mark.asyncio
async def test_an_unknown_crew_is_rejected(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.post(
        "/projects/commit-api-test/commits",
        json={"crew_name": "not_a_crew", "notes": ""},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_readiness_endpoint_reflects_commits(client):
    await client.post("/projects", json=PROJECT)
    before = (await client.get("/projects/commit-api-test/crew-readiness")).json()
    assert before["assessment_design"]["ready"] is False
    assert before["assessment_design"]["waiting_on"] == ["discovery_mapping"]

    await client.post(
        "/projects/commit-api-test/commits",
        json={"crew_name": "discovery_mapping", "notes": ""},
    )
    after = (await client.get("/projects/commit-api-test/crew-readiness")).json()
    assert after["assessment_design"]["ready"] is True
    assert after["assessment_design"]["waiting_on"] == []


@pytest.mark.asyncio
async def test_commit_history_is_returned_newest_first(client):
    await client.post("/projects", json=PROJECT)
    for crew in ("discovery_mapping", "discovery"):
        await client.post(
            "/projects/commit-api-test/commits", json={"crew_name": crew, "notes": ""}
        )
    history = (await client.get("/projects/commit-api-test/commits")).json()
    assert [c["crew_name"] for c in history] == ["discovery", "discovery_mapping"]
    assert history[0]["committed_by"] == "admin"


@pytest.mark.asyncio
async def test_a_non_sysadmin_without_a_matching_approver_is_refused():
    """The rule that will bite once real accounts exist."""
    from httpx import ASGITransport, AsyncClient

    from api.auth import create_access_token
    from api.main import app

    token = create_access_token("nobody", "consultant", "test-secret")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        resp = await ac.post(
            "/projects/commit-api-test/commits",
            json={"crew_name": "discovery_mapping", "notes": ""},
        )
    assert resp.status_code == 403
