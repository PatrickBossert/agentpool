# tests/test_my_permissions.py
"""What the caller may do, asked once rather than inferred from a refusal.

Authority is read from caller_roles(slug, payload) - the walk from JWT to user to
membership to the stakeholder row that carries the person's role flags. This endpoint
reports that same decision so the UI can offer only what the server would accept. It
deliberately does not re-implement the rule: a second copy would drift, and the copy
the UI trusted would be the wrong one.

seeded_project_slug follows tests/test_approve_gate.py's seeded_ledger_script: the client
fixture in conftest.py is an async httpx client against the real app, so every call here is
awaited, and the db file is removed before and after rather than trusting a fresh tmp_path -
DATABASE_DIR is the process-wide /tmp/agentpool_test set in conftest.py, which persists
between runs.
"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from api.config import get_settings
from api.database import get_connection

SLUG = "my-permissions-test"


@pytest_asyncio.fixture
async def seeded_project_slug():
    settings = get_settings()
    db_path = Path(settings.database_dir) / f"{SLUG}.db"
    db_path.unlink(missing_ok=True)

    async with get_connection(SLUG) as conn:
        await conn.execute("INSERT INTO projects (slug) VALUES (?)", (SLUG,))
        await conn.commit()

    yield SLUG

    db_path.unlink(missing_ok=True)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_it_reports_what_the_shared_authority_check_says(client, seeded_project_slug):
    slug = seeded_project_slug
    with patch("api.routers.permissions.caller_roles",
               new=AsyncMock(return_value={"reviewer"})) as gate:
        r = await client.get(f"/projects/{slug}/my-permissions")
    assert r.status_code == 200, r.text
    assert r.json() == {"can_review": True, "can_approve": False}
    # The roles the response is built from are the rule; the booleans are only its shadow.
    gate.assert_awaited_once()
    assert gate.await_args.args[0] == slug
    # And the caller it asked about, not just the project - the client fixture's token
    # names "admin" as a sysadmin; asserting only the slug would pass identically if the
    # endpoint asked caller_roles about the wrong person.
    assert gate.await_args.args[1]["sub"] == "admin"
    assert gate.await_args.args[1]["role"] == "sysadmin"


@pytest.mark.asyncio
async def test_a_caller_with_no_roles_is_told_so(client, seeded_project_slug):
    slug = seeded_project_slug
    with patch("api.routers.permissions.caller_roles",
               new=AsyncMock(return_value=set())):
        r = await client.get(f"/projects/{slug}/my-permissions")
    assert r.json() == {"can_review": False, "can_approve": False}


@pytest.mark.asyncio
async def test_an_unknown_project_is_404_not_a_silent_false(client):
    r = await client.get("/projects/no-such-project/my-permissions")
    assert r.status_code == 404, r.text
