# tests/test_review_intent.py
"""The reviewer's intent is captured with their words, or defaults to the harmless one."""
import pytest

SLUG = "review-intent-test"
PROJECT = {
    "client_slug": SLUG, "llm_mode": "standard", "sector": "utilities",
    "stakeholder_groups": [], "value_stream_labels": [], "review_gates": True, "slack_channel": "",
}

@pytest.fixture(autouse=True)
def _granted_authority():
    """This module is about how an intent is recorded, not about who may record one. The
    client fixture's sysadmin token names no real user, so caller_may_contribute correctly
    answers False for it and the PATCH door would 403 first.

    Not a weakening of the gate: tests/test_write_door_authority.py drives every one of
    these doors over HTTP as a real member with and without the flag, so deleting the gate
    fails there. Patched on the router module, where the name is looked up - the routers
    bind their own reference via `from ... import`, so patching authority_service itself
    would miss them (CLAUDE.md's four-crew-tests entry).
    """
    from unittest.mock import AsyncMock, patch

    with patch("api.routers.reviews.caller_may_contribute", new=AsyncMock(return_value=True)):
        yield


async def _seed_review(client) -> tuple[int, int]:
    """Create a project with one output and one pending review. Returns (review_id, output_id)."""
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection

    async with get_connection(SLUG) as conn:
        cur = await conn.execute(
            "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
            " version, is_current, review_status)"
            " VALUES (1,'value_chain_mapper','value_chain_model','m_v1.json',1,1,'pending')"
        )
        output_id = cur.lastrowid
        cur = await conn.execute(
            "INSERT INTO human_reviews (output_id, decision) VALUES (?, 'pending')",
            (output_id,),
        )
        review_id = cur.lastrowid
        await conn.commit()
    return review_id, output_id


@pytest.mark.asyncio
async def test_intent_is_recorded_against_the_output(client):
    review_id, output_id = await _seed_review(client)

    resp = await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "changes_requested", "notes": "ISS only maintains property",
              "intent": "correction"},
    )
    assert resp.status_code == 200

    from api.database import get_connection

    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT kind, request FROM output_changes WHERE output_id=?", (output_id,)
        )
    assert tuple(rows[0]) == ("correction", "ISS only maintains property")


@pytest.mark.asyncio
async def test_no_intent_given_defaults_to_change_request(client):
    """The default is the option with no persistence beyond the next run. A reviewer in a
    hurry must not be able to seed project truth or the global library by accident."""
    review_id, output_id = await _seed_review(client)

    await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "changes_requested", "notes": "tighten the summary"},
    )

    from api.database import get_connection

    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT kind FROM output_changes WHERE output_id=?", (output_id,)
        )
    assert rows[0][0] == "change_request"


@pytest.mark.asyncio
async def test_approving_records_no_change(client):
    """An approval is not feedback. Recording one would inject an instruction to do nothing."""
    review_id, output_id = await _seed_review(client)

    await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "approved", "notes": ""},
    )

    from api.database import get_connection

    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT COUNT(*) FROM output_changes WHERE output_id=?", (output_id,)
        )
    assert rows[0][0] == 0


@pytest.mark.asyncio
async def test_an_unknown_intent_is_rejected(client):
    review_id, _ = await _seed_review(client)

    resp = await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "changes_requested", "notes": "x", "intent": "whatever"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_approving_with_notes_still_records_no_change(client):
    """Non-empty notes are the whole point of this test: the guard must key on the
    decision, not on whether notes are present. With empty notes, a guard of
    `if req.notes.strip()` and the correct `if decision == "changes_requested" and
    req.notes.strip()` are indistinguishable - both skip recording. Only a non-empty
    note on an approval tells them apart. Without this case, someone could collapse
    the guard to key on notes alone and every existing test would still pass, while
    approvals carrying notes would silently start recording change requests -
    instructions that say nothing, injected into every subsequent run."""
    review_id, output_id = await _seed_review(client)

    await client.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "approved", "notes": "do this anyway"},
    )

    from api.database import get_connection

    async with get_connection(SLUG) as conn:
        rows = await conn.execute_fetchall(
            "SELECT COUNT(*) FROM output_changes WHERE output_id=?", (output_id,)
        )
    assert rows[0][0] == 0
