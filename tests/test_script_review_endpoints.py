# tests/test_script_review_endpoints.py
"""Per-script review endpoints: authority, the approve/send-back split, and the ledger read.

seeded_script is written against tests/conftest.py's own `client` fixture rather than the
project fixture(s) task-4's tests use: `client` is an async httpx client running against the
real app (api.main.app under a sysadmin token), so every call here is awaited and every
assertion is scoped to the one script this fixture created - never to a global count, and
never to a hardcoded row id outside this fixture's own project, per CLAUDE.md's rerun trap.

PRAGMA foreign_keys = ON on every project connection, so the ledger row is only ever
inserted after its projects row exists.
"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from api.config import get_settings
from api.database import get_connection

SLUG = "script-review-endpoint-test"


@pytest_asyncio.fixture
async def seeded_script():
    """One project, one ledger row (SC-001), scoped to its own db file.

    The db file is removed before and after the test rather than relying on a fresh
    tmp_path: DATABASE_DIR is the process-wide /tmp/agentpool_test set in conftest.py,
    which persists between runs, so leftover state from a previous run must not be able
    to make this fixture's INSERT collide with an already-approved row from last time.
    """
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)

    async with get_connection(SLUG) as conn:
        await conn.execute("INSERT INTO projects (slug) VALUES (?)", (SLUG,))
        await conn.commit()
        cur = await conn.execute("SELECT id FROM projects WHERE slug=?", (SLUG,))
        project_id = (await cur.fetchone())["id"]
        await conn.execute(
            "INSERT INTO interview_script_ledger"
            " (script_id, project_id, node_id, last_version, last_author)"
            " VALUES ('SC-001', ?, '1.2', 3, 'maya')",
            (project_id,),
        )
        await conn.commit()

    yield SLUG, "SC-001"

    db_path.unlink(missing_ok=True)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_reviewing_a_script_requires_reviewer_or_approver_authority(client, seeded_script):
    """Authority comes from the stakeholder assignment - is_reviewer / is_approver - not
    from the login role. Reuses _caller_matches_stakeholder_flag so there is exactly one
    place this rule lives.

    Asserted by denying the gate rather than by accepting whatever the endpoint returns.
    _caller_matches_stakeholder_flag returns True for sysadmin, and today every login is
    sysadmin against an empty users table, so a live call always succeeds - a test that
    accepted either 200 or 403 would pass with the gate deleted.
    """
    slug, script_id = seeded_script
    with patch("api.routers.script_reviews._caller_matches_stakeholder_flag",
               new=AsyncMock(return_value=False)):
        r = await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                               json={"decision": "reviewed"})
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_approving_asks_for_approver_authority_and_reviewing_asks_for_either(
        client, seeded_script):
    """Which flags are demanded is the rule; the status code is only its shadow. Patched
    where the name is looked up - api.routers.script_reviews - not where it is defined,
    because the router binds its own reference with `from ... import`."""
    slug, script_id = seeded_script
    with patch("api.routers.script_reviews._caller_matches_stakeholder_flag",
               new=AsyncMock(return_value=True)) as gate:
        await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                           json={"decision": "reviewed"})
        assert gate.call_args.kwargs["flags"] == ("is_reviewer", "is_approver")
        await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                           json={"decision": "approved"})
        assert gate.call_args.kwargs["flags"] == ("is_approver",)


@pytest.mark.asyncio
async def test_approving_twice_is_refused_with_409(client, seeded_script):
    slug, script_id = seeded_script
    first = await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                               json={"decision": "approved"})
    assert first.status_code == 200, first.text
    r = await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                           json={"decision": "approved"})
    assert r.status_code == 409, r.text
    assert "already approved" in r.text


@pytest.mark.asyncio
async def test_a_send_back_without_a_target_is_refused_with_422(client, seeded_script):
    slug, script_id = seeded_script
    r = await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                           json={"decision": "changes_requested", "notes": "no"})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_the_ledger_endpoint_returns_status_and_staleness_inputs(client, seeded_script):
    """The UI computes staleness from reviewed_at_version against last_version, so both
    must be on the wire - a server-side boolean would be stale the moment a write landed
    between the query and the render."""
    slug, script_id = seeded_script
    r = await client.get(f"/projects/{slug}/script-ledger")
    assert r.status_code == 200
    rows = {row["script_id"]: row for row in r.json()}
    assert script_id in rows
    row = rows[script_id]
    for field in ("script_id", "node_id", "review_status",
                  "reviewed_at_version", "last_version", "last_author"):
        assert field in row
