# tests/test_approve_gate.py
"""A disabled button is a hint. The gate has to hold at the endpoint or it is decoration.

seeded_ledger_script follows tests/test_script_review_endpoints.py's seeded_script: the
`client` fixture in conftest.py is an async httpx client against the real app, so every
call here is awaited, and PRAGMA foreign_keys = ON means the projects row goes in before
the ledger row. Assertions are scoped to the one script this fixture created.
"""
from pathlib import Path

import pytest
import pytest_asyncio

from api.config import get_settings
from api.database import get_connection

SLUG = "approve-gate-test"


@pytest_asyncio.fixture
async def seeded_ledger_script():
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
async def test_approving_an_unreviewed_script_is_refused(client, seeded_ledger_script):
    slug, script_id = seeded_ledger_script
    r = await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                           json={"decision": "approved"})
    assert r.status_code == 409, r.text
    assert "no reviews" in r.text.lower()


@pytest.mark.asyncio
async def test_approving_is_permitted_once_the_script_has_been_reviewed(
        client, seeded_ledger_script):
    slug, script_id = seeded_ledger_script
    first = await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                               json={"decision": "reviewed"})
    assert first.status_code == 200, first.text

    # Wire-level check on review_count: the endpoint's sibling that a later task gates
    # the Approve button on. A count that is correct in the service and missing from the
    # response would fail one layer from where anybody would look.
    ledger = await client.get(f"/projects/{slug}/script-ledger")
    assert ledger.status_code == 200, ledger.text
    row = {r["script_id"]: r for r in ledger.json()}[script_id]
    assert row["review_count"] == 1

    r = await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                           json={"decision": "approved"})
    assert r.status_code == 200, r.text
    assert r.json()["review_status"] == "approved"


@pytest.mark.asyncio
async def test_the_approvers_own_review_satisfies_the_gate(client, seeded_ledger_script):
    """A smaller engagement may have one person holding both roles. Someone who opened a
    script, read it, and marked it reviewed has genuinely read it - the gate asks whether it
    has been read, not whether somebody else read it."""
    slug, script_id = seeded_ledger_script
    await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                       json={"decision": "reviewed"})
    r = await client.post(f"/projects/{slug}/script-ledger/{script_id}/review",
                           json={"decision": "approved"})
    assert r.status_code == 200, r.text
