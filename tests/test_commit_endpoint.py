# tests/test_commit_endpoint.py
"""Committing a crew's outputs, and who is allowed to.

The identity model cannot yet express "only approvers commit": the users table is
empty and every login is sysadmin. The rule is written so it is correct now and
tightens by itself once per-user accounts exist.
"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from api.config import get_settings
from api.database import get_connection

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
    # Each test commits against the same slug, and the readiness and auto-start
    # assertions depend on that project starting with no prior commits or runs - so the
    # db is wiped before and after every test, mirroring tests/test_approval_commits.py.
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
async def test_committing_starts_the_crew_below_it(client):
    await client.post("/projects", json=PROJECT)
    await client.post("/projects/commit-api-test/activate")

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        resp = await client.post(
            "/projects/commit-api-test/commits",
            json={"crew_name": "discovery_mapping", "notes": ""},
        )

    started = [s["crew"] for s in resp.json()["started"]]
    assert started == ["assessment_design"]


@pytest.mark.asyncio
async def test_a_second_commit_starts_the_downstream_crew_again(client):
    """The behaviour this project exists for. The old `released` field reported a crew
    only the first time it became ready, so approving a revision started nothing."""
    await client.post("/projects", json=PROJECT)
    await client.post("/projects/commit-api-test/activate")

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        first = await client.post(
            "/projects/commit-api-test/commits",
            json={"crew_name": "discovery_mapping", "notes": ""},
        )
        # The first start leaves assessment_design running, which would mask the second
        # commit as a skip rather than a start. Clear it, as a finished run would.
        async with get_connection("commit-api-test") as conn:
            await conn.execute(
                "UPDATE crew_runs SET status='completed' WHERE crew_name='assessment_design'"
            )
            await conn.commit()
        second = await client.post(
            "/projects/commit-api-test/commits",
            json={"crew_name": "discovery_mapping", "notes": ""},
        )

    assert [s["crew"] for s in first.json()["started"]] == ["assessment_design"]
    assert [s["crew"] for s in second.json()["started"]] == ["assessment_design"]


@pytest.mark.asyncio
async def test_a_crew_waiting_on_another_upstream_is_reported_not_started(client):
    """discovery_interviews needs both assessment_design and stakeholder_management."""
    await client.post("/projects", json=PROJECT)
    await client.post("/projects/commit-api-test/activate")

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        resp = await client.post(
            "/projects/commit-api-test/commits",
            json={"crew_name": "assessment_design", "notes": ""},
        )

    waiting = {w["crew"]: w["waiting_on"] for w in resp.json()["waiting"]}
    assert waiting["discovery_interviews"] == ["stakeholder_management"]


@pytest.mark.asyncio
async def test_an_inactive_project_commits_without_starting_anything(client):
    """The commit must still land - only the start is suppressed."""
    await client.post("/projects", json=PROJECT)

    with patch("api.services.autostart_service.dispatch_crew", AsyncMock()):
        resp = await client.post(
            "/projects/commit-api-test/commits",
            json={"crew_name": "discovery_mapping", "notes": ""},
        )

    body = resp.json()
    assert resp.status_code == 201
    assert body["inactive"] is True
    assert body["started"] == []
    assert isinstance(body["commit_id"], int)


@pytest.mark.asyncio
async def test_the_commit_lands_even_when_starting_raises(client):
    """An approval that was recorded stays recorded whatever happens next."""
    await client.post("/projects", json=PROJECT)
    await client.post("/projects/commit-api-test/activate")

    with patch(
        "api.routers.commits.start_ready_downstream",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        resp = await client.post(
            "/projects/commit-api-test/commits",
            json={"crew_name": "discovery_mapping", "notes": ""},
        )

    assert resp.status_code == 201
    commits = await client.get("/projects/commit-api-test/commits")
    assert len(commits.json()) == 1

    # And it says so. Reporting three empty lists with inactive=False would assert that
    # the project is active and that no crew is waiting - neither of which is known when
    # the call that would have established them is what raised.
    body = resp.json()
    assert body["autostart_failed"] is True
    assert "inactive" not in body
    assert "waiting" not in body


@pytest.mark.asyncio
async def test_committing_a_crew_whose_run_is_still_going_is_refused_with_409(client):
    """A commit freezes whichever outputs are current at that moment. Taken mid-run,
    it would freeze a mix of this run's outputs and the last's - a temporary state
    the caller should retry after, hence 409 rather than 422."""
    await client.post("/projects", json=PROJECT)

    from api.database import fetch_project, get_connection, insert_crew_run
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        await insert_crew_run(
            conn, project_id=project["id"], crew_name="discovery_mapping", status="running"
        )

    resp = await client.post(
        "/projects/commit-api-test/commits",
        json={"crew_name": "discovery_mapping", "notes": ""},
    )
    assert resp.status_code == 409
    assert "discovery_mapping" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_the_same_commit_succeeds_once_the_run_has_completed(client):
    await client.post("/projects", json=PROJECT)

    from api.database import fetch_project, get_connection, insert_crew_run, update_crew_run_status
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        run_id = await insert_crew_run(
            conn, project_id=project["id"], crew_name="discovery_mapping", status="running"
        )
        await update_crew_run_status(conn, run_id=run_id, status="completed")

    resp = await client.post(
        "/projects/commit-api-test/commits",
        json={"crew_name": "discovery_mapping", "notes": ""},
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_a_different_crew_running_does_not_block_this_commit(client):
    await client.post("/projects", json=PROJECT)

    from api.database import fetch_project, get_connection, insert_crew_run
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        await insert_crew_run(
            conn, project_id=project["id"], crew_name="assessment_design", status="running"
        )

    resp = await client.post(
        "/projects/commit-api-test/commits",
        json={"crew_name": "discovery_mapping", "notes": ""},
    )
    assert resp.status_code == 201


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
async def test_a_role_with_no_project_access_is_refused_before_approval_is_checked():
    """check_project_access, not caller_may_commit, is what stops this caller.

    A "consultant" role matches none of check_project_access's branches
    (sysadmin / org_admin-of-this-project / reviewer-with-membership), so it 403s
    before the handler ever asks whether the caller may commit. This is project-access
    gating, not the approver rule - see test_caller_may_commit_matches_approver_by_email
    below for a case that actually reaches caller_may_commit.
    """
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


@pytest.mark.asyncio
async def test_caller_may_commit_matches_approver_by_email(client):
    """The rule that will bite once real accounts exist.

    A "reviewer" with project membership clears check_project_access, so this
    exercises caller_may_commit itself: refused while no stakeholder record matches
    the caller's account email as an approver, then let through once one exists.
    Proving both halves matters - a caller_may_commit that always returned False
    would still pass a 403-only test.
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
    )
    from api.main import app

    await client.post("/projects", json=PROJECT)

    username = "commit-api-reviewer"
    email = "commit-api-reviewer@example.com"
    async with get_system_connection() as sys_conn:
        await insert_user(
            sys_conn, username=username, email=email, role="reviewer", hashed_pw="x"
        )
        user = await fetch_user(sys_conn, username=username)
        await insert_project_membership(sys_conn, user_id=user["id"], project_slug=SLUG)

    token = create_access_token(username, "reviewer", "test-secret")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        # No stakeholder yet matches this caller's email as an approver.
        refused = await ac.post(
            "/projects/commit-api-test/commits",
            json={"crew_name": "discovery_mapping", "notes": ""},
        )
        assert refused.status_code == 403

        # StakeholderIn (api/routers/stakeholders.py:45-46) does declare is_reviewer
        # and is_approver, so posting through the endpoint would work too - but going
        # straight to the database keeps this a unit test of caller_may_commit, not
        # of the stakeholders endpoint's auth and validation.
        async with get_connection(SLUG) as conn:
            project = await fetch_project(conn, slug=SLUG)
            await insert_stakeholder(
                conn,
                project_id=project["id"],
                name="Reviewer One",
                email=email,
                is_approver=True,
            )

        allowed = await ac.post(
            "/projects/commit-api-test/commits",
            json={"crew_name": "discovery_mapping", "notes": ""},
        )
        assert allowed.status_code == 201
