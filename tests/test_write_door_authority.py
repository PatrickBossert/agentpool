"""Every write door behind check_project_access, driven over HTTP as a real member.

check_project_access answers "does this account belong to this engagement". Membership is
read access by design, so that is the whole of what it asks - its reviewer branch returns
successfully on a project_memberships row with no role test at all. Before this branch
that was safe by accident: `users` held no rows, so the principal class "authenticated
non-admin with a project membership" was empty and nothing could reach those doors. The
invite loop creates that class - every accepted invite mints role="reviewer" - so each
door that writes now has to ask the authority walk as well.

The two callers below are the only shape that proves it. `member` holds a stakeholder row
flagged is_participant and nothing else: a real, fully-wired login (users row, membership,
stakeholder, project all present) that clears check_project_access and must still be
refused. `approver` is the same wiring with is_reviewer and is_approver set. A test that
called caller_roles directly would prove the walk works and say nothing about whether any
door consults it - the failure mode CLAUDE.md names, a property asserted one layer away
from where it holds.
"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.auth import create_access_token
from api.config import get_settings
from api.database import (
    fetch_project,
    fetch_user,
    get_connection,
    get_system_connection,
    insert_agent_output,
    insert_review,
    insert_stakeholder,
    insert_user,
    link_membership,
)

SLUG = "write-door-authority"

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

MODEL = {"segments": []}


async def _client_for(username: str) -> AsyncClient:
    from api.main import app

    token = create_access_token(username, "reviewer", "test-secret")
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


async def _seed_person(slug: str, *, username: str, email: str, **flags) -> int:
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        stakeholder_id = await insert_stakeholder(
            conn, project_id=project["id"], name=username, email=email, **flags
        )
    async with get_system_connection() as sys_conn:
        await insert_user(
            sys_conn, username=username, email=email, role="reviewer", hashed_pw="x"
        )
        user = await fetch_user(sys_conn, username=username)
        await link_membership(
            sys_conn, user_id=user["id"], project_slug=slug, stakeholder_id=stakeholder_id
        )
    return stakeholder_id


@pytest_asyncio.fixture
async def doors(client):
    """One project, one output to hang reviews off, and two members of it.

    The project is created through the API with the suite's sysadmin token, so the
    fixture exercises the same creation path everything else does. Both people are then
    wired the whole way - users row, membership, stakeholder - because a caller who is
    refused for want of a membership proves nothing about a role gate.
    """
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)

    await client.post("/projects", json=PROJECT)

    await _seed_person(
        SLUG, username="door-participant", email="participant@example.com",
        is_participant=True,
    )
    await _seed_person(
        SLUG, username="door-approver", email="approver@example.com",
        is_reviewer=True, is_approver=True,
    )

    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        output_id = await insert_agent_output(
            conn, project_id=project["id"], agent_name="value_chain_mapper",
            output_type="value_chain_summary",
            file_path=str(Path(settings.database_dir) / "summary_v1.json"),
            version=1,
        )
        review_id = await insert_review(
            conn, output_id=output_id, reviewer="someone else",
            decision="changes_requested", notes="please revisit",
        )
        cur = await conn.execute(
            "INSERT INTO validation_warnings (project_id, source, subject, code, detail)"
            " VALUES (?,?,?,?,?)",
            (project["id"], "coverage_validation", "1.2", "incomplete_coverage",
             "1.2 has no interview script"),
        )
        warning_id = cur.lastrowid
        await conn.commit()

    member = await _client_for("door-participant")
    approver = await _client_for("door-approver")
    async with member, approver:
        yield {
            "member": member,
            "approver": approver,
            "output_id": output_id,
            "review_id": review_id,
            "warning_id": warning_id,
        }

    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


# ── The member clears membership, so these refusals are the role gate and nothing else ──

@pytest.mark.asyncio
async def test_the_member_really_does_hold_membership(doors):
    """The control. Every refusal below is only meaningful if this caller is genuinely
    inside the project - otherwise check_project_access would be doing the refusing and
    the role gates could all be deleted without a single test noticing."""
    resp = await doors["member"].get(f"/projects/{SLUG}/reviews")
    assert resp.status_code == 200, "a member must still be able to read the engagement"
    assert (await doors["member"].get(f"/projects/{SLUG}/outputs")).status_code == 200


@pytest.mark.asyncio
async def test_submitting_a_review_needs_a_role(doors):
    body = {"output_id": doors["output_id"], "decision": "changes_requested", "notes": "no"}
    assert (await doors["member"].post(f"/projects/{SLUG}/review", json=body)).status_code == 403
    assert (await doors["approver"].post(f"/projects/{SLUG}/review", json=body)).status_code == 201


@pytest.mark.asyncio
async def test_resolving_a_review_needs_a_role(doors):
    path = f"/projects/{SLUG}/reviews/{doors['review_id']}"
    body = {"decision": "changes_requested", "notes": "still not right"}
    assert (await doors["member"].patch(path, json=body)).status_code == 403
    assert (await doors["approver"].patch(path, json=body)).status_code == 200


@pytest.mark.asyncio
async def test_deleting_a_review_needs_approval(doors):
    path = f"/projects/{SLUG}/reviews/{doors['review_id']}"
    assert (await doors["member"].delete(path)).status_code == 403
    assert (await doors["approver"].delete(path)).status_code == 204


@pytest.mark.asyncio
async def test_requesting_a_change_needs_a_role(doors):
    body = {"output_id": doors["output_id"], "request": "rename the second segment"}
    assert (await doors["member"].post(f"/projects/{SLUG}/changes", json=body)).status_code == 403
    assert (await doors["approver"].post(f"/projects/{SLUG}/changes", json=body)).status_code == 201


@pytest.mark.asyncio
async def test_disposing_of_a_validation_warning_needs_a_role(doors):
    path = f"/projects/{SLUG}/validation-warnings/{doors['warning_id']}"
    body = {"disposition": "dismissed", "note": "the node was retired last week"}
    assert (await doors["member"].patch(path, json=body)).status_code == 403
    assert (await doors["approver"].patch(path, json=body)).status_code == 200


@pytest.mark.asyncio
async def test_saving_the_value_chain_model_needs_approval(doors):
    path = f"/projects/{SLUG}/value-chain-model"
    body = {"model": MODEL, "summary": "tidied"}
    assert (await doors["member"].put(path, json=body)).status_code == 403
    assert (await doors["approver"].put(path, json=body)).status_code == 200


@pytest.mark.asyncio
async def test_migrating_the_value_chain_model_needs_approval(doors):
    """The refusal is what is asserted for the member. The approver's own call is not
    asserted as a success - this project has no registry to migrate from, so it answers
    422 either way - only that it is no longer the 403, which is what distinguishes "the
    gate let them through" from "the gate is refusing everyone"."""
    path = f"/projects/{SLUG}/value-chain-model/migrate"
    assert (await doors["member"].post(path)).status_code == 403
    assert (await doors["approver"].post(path)).status_code != 403


@pytest.mark.asyncio
async def test_reverting_an_output_needs_approval(doors):
    path = f"/projects/{SLUG}/outputs/{doors['output_id']}/revert"
    assert (await doors["member"].post(path)).status_code == 403
    assert (await doors["approver"].post(path)).status_code == 200


@pytest.mark.asyncio
async def test_adding_a_discovery_link_needs_approval(doors):
    path = f"/projects/{SLUG}/agent-chat/link"
    body = {
        "agent_name": "value_chain_mapper",
        "url": "https://example.com/strategy",
        "label": "Strategy",
    }
    assert (await doors["member"].post(path, json=body)).status_code == 403
    # The approver's call reaches the fetch, which has no network here - what matters is
    # only that authority no longer stops it.
    assert (await doors["approver"].post(path, json=body)).status_code != 403


@pytest.mark.asyncio
async def test_attaching_a_document_through_chat_needs_approval(doors):
    """POST /{slug}/documents/upload has always been require_org_admin_or_above. This
    door writes the same documents row, the same discovery_document_ids entry, and the
    same Chroma ingest - it had become the weaker way through.

    The approver's 201 is half the test, not decoration. Without it this asserted only a
    refusal, which an unconditional refusal wired onto this one door satisfies perfectly -
    and tests/test_chat_upload.py, the only other module driving this endpoint, patches
    caller_may_approve to True for every one of its cases, so it would not have noticed
    either. ingest_document is patched because Chroma is not running here; the gate under
    test sits well before it.
    """
    path = f"/projects/{SLUG}/agent-chat/upload"
    files = {"file": ("brief.txt", b"a paragraph", "text/plain")}
    data = {"agent_name": "value_chain_mapper"}
    with patch("api.routers.agent_chat.ingest_document", new_callable=AsyncMock):
        refused = await doors["member"].post(path, files=files, data=data)
        allowed = await doors["approver"].post(path, files=files, data=data)
    assert refused.status_code == 403
    assert allowed.status_code == 201
