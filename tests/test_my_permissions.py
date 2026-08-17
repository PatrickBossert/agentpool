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
    # can_grant_roles is not built from the patched set: it asks
    # caller_may_grant_project_roles, which recognises the platform administrator off the
    # token (see its docstring - the built-in admin has no `users` row for the walk to
    # read). The client fixture is that administrator, so True is the honest answer here.
    # tests/test_grantable_roles.py drives it against real per-project roles.
    # can_issue_invite_links is the platform tier read off the token, for the same reason:
    # the resend door it reports on is `require_org_admin_or_above`, not the walk. The
    # client fixture's token says sysadmin, so True. tests/test_grantable_roles.py drives
    # it against the door itself.
    assert r.json() == {
        "can_review": True, "can_approve": False, "can_grant_roles": True,
        "can_issue_invite_links": True,
    }
    # The roles the response is built from are the rule; the booleans are only its shadow.
    gate.assert_awaited_once()
    assert gate.await_args.args[0] == slug
    # And the caller it asked about, not just the project - the client fixture's token
    # names "admin" as a sysadmin; asserting only the slug would pass identically if the
    # endpoint asked caller_roles about the wrong person.
    assert gate.await_args.args[1]["sub"] == "admin"
    assert gate.await_args.args[1]["role"] == "sysadmin"


@pytest.mark.asyncio
async def test_a_caller_with_no_content_roles_is_told_so(client, seeded_project_slug):
    """The walk answering an empty set means no content authority - and says nothing about
    can_grant_roles, which asks `caller_may_grant_project_roles` rather than this patched
    set. The client fixture is the platform administrator, so True is the honest answer for
    it; the name says "no *content* roles" because that is all this patch controls.

    tests/test_grantable_roles.py::test_my_permissions_reports_the_grant_right_the_door_enforces
    drives can_grant_roles against real per-project roles, unpatched.
    """
    slug = seeded_project_slug
    with patch("api.routers.permissions.caller_roles",
               new=AsyncMock(return_value=set())):
        r = await client.get(f"/projects/{slug}/my-permissions")
    assert r.json() == {
        "can_review": False, "can_approve": False, "can_grant_roles": True,
        "can_issue_invite_links": True,
    }


@pytest.mark.asyncio
async def test_an_unknown_project_is_404_not_a_silent_false(client):
    r = await client.get("/projects/no-such-project/my-permissions")
    assert r.status_code == 404, r.text
