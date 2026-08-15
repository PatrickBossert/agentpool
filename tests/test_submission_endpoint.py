"""Submitting a crew for approval, reading crew states, and activating a project.

Submitting is wider than committing: a contributor who reviews but does not govern
may submit, but only an approver may commit or activate. The paired test below is
what proves both rules are right - without it either could be inverted and the suite
would not notice.

Authority is read from caller_roles(slug, payload) - see api/services/authority_service.py.
Only test_a_reviewer_may_submit_but_not_commit exercises that rule directly; every other
test here is about the submission/activation machinery, so caller_may_commit and
caller_may_submit are granted throughout by the autouse fixture below - the client
fixture's sysadmin token names no real user, so an unpatched call would 403 first.
"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from api.config import get_settings

SLUG = "submit-test"


@pytest.fixture(autouse=True)
def _granted_approver(request):
    if "real_authority" in request.keywords:
        # This test proves caller_may_commit / caller_may_submit themselves - patching
        # them here would make the thing under test into the thing granting the pass.
        yield
        return
    with patch("api.routers.commits.caller_may_commit", new=AsyncMock(return_value=True)), \
         patch("api.routers.commits.caller_may_submit", new=AsyncMock(return_value=True)):
        yield
PROJECT = {
    "client_slug": "submit-test",
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
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_submitting_moves_a_crew_to_ready(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.post(
        f"/projects/{SLUG}/submissions",
        json={"crew_name": "discovery_mapping", "notes": "labels tidied"},
    )
    assert resp.status_code == 201

    states = (await client.get(f"/projects/{SLUG}/crew-states")).json()
    assert states["discovery_mapping"] == "ready"


@pytest.mark.asyncio
async def test_approving_a_submitted_crew_moves_it_to_committed(client):
    await client.post("/projects", json=PROJECT)
    await client.post(
        f"/projects/{SLUG}/submissions", json={"crew_name": "discovery_mapping"}
    )
    await client.post(
        f"/projects/{SLUG}/commits", json={"crew_name": "discovery_mapping"}
    )
    states = (await client.get(f"/projects/{SLUG}/crew-states")).json()
    assert states["discovery_mapping"] == "committed"


@pytest.mark.asyncio
async def test_an_unknown_crew_cannot_be_submitted(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.post(
        f"/projects/{SLUG}/submissions", json={"crew_name": "not_a_crew"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_activation_sets_the_project_active(client):
    await client.post("/projects", json=PROJECT)
    resp = await client.post(f"/projects/{SLUG}/activate")
    assert resp.status_code == 200

    from api.database import get_connection, fetch_project
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
    assert project["status"] == "active"


@pytest.mark.asyncio
async def test_activating_twice_is_harmless(client):
    await client.post("/projects", json=PROJECT)
    await client.post(f"/projects/{SLUG}/activate")
    assert (await client.post(f"/projects/{SLUG}/activate")).status_code == 200


@pytest.mark.asyncio
@pytest.mark.real_authority
async def test_a_reviewer_may_submit_but_not_commit(client):
    """The pairing that proves both permission rules are right.

    A reviewer who does not govern clears check_project_access via project
    membership, and caller_roles walks that membership to a stakeholder flagged
    is_reviewer - so caller_may_submit lets the submission through. That same
    stakeholder is not flagged is_approver, so caller_may_commit still refuses.
    Without this pairing, either rule could be wrong and the suite would not notice.
    """
    from httpx import ASGITransport, AsyncClient

    from api.auth import create_access_token
    from api.database import (
        fetch_project,
        fetch_user,
        get_connection,
        get_system_connection,
        insert_project_membership,
        insert_stakeholder,
        insert_user,
        link_membership,
    )
    from api.main import app

    await client.post("/projects", json=PROJECT)

    username = "submit-test-reviewer"
    email = "submit-test-reviewer@example.com"
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        stakeholder_id = await insert_stakeholder(
            conn,
            project_id=project["id"],
            name="Reviewer One",
            email=email,
            is_reviewer=True,
            is_approver=False,
        )

    async with get_system_connection() as sys_conn:
        await insert_user(
            sys_conn, username=username, email=email, role="reviewer", hashed_pw="x"
        )
        user = await fetch_user(sys_conn, username=username)
        await insert_project_membership(sys_conn, user_id=user["id"], project_slug=SLUG)
        await link_membership(
            sys_conn, user_id=user["id"], project_slug=SLUG, stakeholder_id=stakeholder_id
        )

    token = create_access_token(username, "reviewer", "test-secret")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        submitted = await ac.post(
            f"/projects/{SLUG}/submissions",
            json={"crew_name": "discovery_mapping", "notes": ""},
        )
        assert submitted.status_code == 201

        committed = await ac.post(
            f"/projects/{SLUG}/commits",
            json={"crew_name": "discovery_mapping", "notes": ""},
        )
        assert committed.status_code == 403
