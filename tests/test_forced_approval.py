# tests/test_forced_approval.py
"""An approver may override the gate, and the record must show they did.

Without this, approved silently means two different things - "two people looked at this"
and "one person waved it through" - and six months later nobody can tell which. The warning
in the UI is a courtesy; the audit trail is the point.
"""
import pytest

from tests.test_approve_gate import _granted_approver, seeded_ledger_script  # noqa: F401


@pytest.mark.asyncio
async def test_an_unforced_approval_on_an_unreviewed_script_is_still_refused(
        client, seeded_ledger_script):
    slug, script_id = seeded_ledger_script
    r = await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                          json={"decision": "approved"})
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_a_forced_approval_is_permitted_and_recorded_as_forced(
        client, seeded_ledger_script):
    slug, script_id = seeded_ledger_script
    r = await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                          json={"decision": "approved", "forced": True})
    assert r.status_code == 200, r.text

    from api.database import get_connection
    async with get_connection(slug) as conn:
        cur = await conn.execute(
            "SELECT decision, forced FROM script_reviews WHERE script_id=?", (script_id,))
        rows = [tuple(x) for x in await cur.fetchall()]
    assert rows == [("approved", 1)]


@pytest.mark.asyncio
async def test_a_normal_approval_after_a_review_is_not_marked_forced(
        client, seeded_ledger_script):
    slug, script_id = seeded_ledger_script
    await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                      json={"decision": "reviewed"})
    await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                      json={"decision": "approved"})
    from api.database import get_connection
    async with get_connection(slug) as conn:
        cur = await conn.execute(
            "SELECT forced FROM script_reviews WHERE decision='approved'")
        assert [r[0] for r in await cur.fetchall()] == [0]
