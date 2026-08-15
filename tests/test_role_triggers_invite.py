# tests/test_role_triggers_invite.py
"""The trigger is the data, not a step somebody has to remember.

Setting any role other than participant on a person with no login issues an invite -
whether they were typed in or bulk-uploaded, because both paths end at the same write.

seeded_project_slug follows tests/test_my_permissions.py's fixture of the same name: the
client fixture in conftest.py is an async httpx client against the real app, and
DATABASE_DIR is the process-wide /tmp/agentpool_test set in conftest.py, which persists
between runs - so the db file is removed before and after rather than trusting a fresh
tmp_path.
"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from api.config import get_settings
from api.database import get_connection

SLUG = "role-triggers-invite-test"


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
async def test_adding_a_participant_issues_no_invite(client, seeded_project_slug):
    slug = seeded_project_slug
    with patch("api.routers.stakeholders.issue_invite", new=AsyncMock()) as invite:
        r = await client.post(f"/projects/{slug}/stakeholders",
                              json={"name": "Ana", "email": "ana@example.com",
                                    "is_participant": True})
    assert r.status_code in (200, 201), r.text
    invite.assert_not_awaited()


@pytest.mark.asyncio
async def test_setting_a_reviewer_role_issues_exactly_one_invite(client, seeded_project_slug):
    slug = seeded_project_slug
    with patch("api.routers.stakeholders.issue_invite", new=AsyncMock()) as invite:
        r = await client.post(f"/projects/{slug}/stakeholders",
                              json={"name": "Bo", "email": "bo@example.com",
                                    "is_reviewer": True})
        assert r.status_code in (200, 201), r.text
        sid = r.json()["id"]
        await client.patch(f"/projects/{slug}/stakeholders/{sid}",
                           json={"is_approver": True})
    assert invite.await_count == 1, "a second role must not issue a second invite"
    assert invite.await_args.kwargs["email"] == "bo@example.com"


@pytest.mark.asyncio
async def test_a_person_with_no_email_cannot_be_invited_and_says_so(client, seeded_project_slug):
    """Dougie McCrone holds full rights on the live project and has no address, so nothing
    can reach him and nothing reports it. A role set on an addressless person must surface
    that rather than silently not sending."""
    slug = seeded_project_slug
    r = await client.post(f"/projects/{slug}/stakeholders",
                          json={"name": "Dougie", "email": "", "is_reviewer": True})
    assert r.status_code == 422, r.text
    assert "email" in r.text.lower()
