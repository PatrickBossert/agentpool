# tests/test_role_triggers_invite.py
"""The trigger is the data, not a step somebody has to remember.

Setting any role other than participant on a person with no login issues an invite -
whether they were typed in or bulk-uploaded, because both paths end at the same write.

seeded_project_slug follows tests/test_my_permissions.py's fixture of the same name: the
client fixture in conftest.py is an async httpx client against the real app, and
DATABASE_DIR is the process-wide /tmp/agentpool_test set in conftest.py, which persists
between runs - so the db file is removed before and after rather than trusting a fresh
tmp_path. (This is now a second copy of that fixture rather than a shared import - recorded,
not fixed, per review.)
"""
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from api.config import get_settings
from api.database import get_connection, get_system_connection, insert_user, link_membership

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


async def _purge_system_login(email: str) -> None:
    """Remove any system-db login (and its memberships) for this email.

    system.db at /tmp/agentpool_test is shared and persistent - unlike seeded_project_slug's
    own per-project database, nothing tears it down between runs. A test that seeds a users
    row to prove the login-check conjunct (_has_linked_login) would otherwise poison its own
    database exactly the way CLAUDE.md warns about: it passes once, and on every run
    afterwards _has_linked_login finds that same leftover row true from the very first
    write, before the test ever reaches the behaviour it means to exercise.
    """
    async with get_system_connection() as conn:
        cur = await conn.execute("SELECT id FROM users WHERE username=?", (email,))
        row = await cur.fetchone()
        if row is None:
            return
        await conn.execute("DELETE FROM project_memberships WHERE user_id=?", (row[0],))
        await conn.execute("DELETE FROM users WHERE id=?", (row[0],))
        await conn.commit()


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
    """The PATCH response is asserted, not just the invite mock - the flagship version of
    this test passed vacuously: a PATCH route that 405s starves the guard of ever being
    exercised a second time, and `await_count == 1` is satisfied identically by "the guard
    works" and by "the second write never happened". Asserting the row actually holds both
    flags is what forces the write to have really landed."""
    slug = seeded_project_slug
    with patch("api.routers.stakeholders.issue_invite", new=AsyncMock()) as invite:
        r = await client.post(f"/projects/{slug}/stakeholders",
                              json={"name": "Bo", "email": "bo@example.com",
                                    "is_reviewer": True})
        assert r.status_code in (200, 201), r.text
        sid = r.json()["id"]
        patch_resp = await client.patch(f"/projects/{slug}/stakeholders/{sid}",
                                        json={"is_approver": True})
    assert patch_resp.status_code == 200, patch_resp.text
    body = patch_resp.json()
    assert body["is_reviewer"] is True
    assert body["is_approver"] is True
    assert invite.await_count == 1, "a second role must not issue a second invite"
    assert invite.await_args.kwargs["email"] == "bo@example.com"


@pytest.mark.asyncio
async def test_a_person_with_no_email_cannot_be_invited_and_says_so(client, seeded_project_slug):
    """Dougie McCrone holds full rights on the live project and has no address, so nothing
    can reach him and nothing reports it. A role set on an addressless person must surface
    that rather than silently not sending.

    issue_invite is patched here too - not because this test asserts on it, but because if
    the 422 ever regresses, the unpatched call would mint a real auth_tokens row with
    email='' into the shared, persistent /tmp/agentpool_test database, exactly the trap
    CLAUDE.md documents, in the one test positioned to trip it.
    """
    slug = seeded_project_slug
    with patch("api.routers.stakeholders.issue_invite", new=AsyncMock()) as invite:
        r = await client.post(f"/projects/{slug}/stakeholders",
                              json={"name": "Dougie", "email": "", "is_reviewer": True})
    assert r.status_code == 422, r.text
    assert "email" in r.text.lower()
    invite.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_invalid_looking_email_cannot_be_invited_and_says_so(client, seeded_project_slug):
    """email is a bare str, not validated as an address anywhere else in this model - and it
    now mints tokens, so garbage reaching issue_invite is a newly real consequence rather
    than a cosmetic one."""
    slug = seeded_project_slug
    with patch("api.routers.stakeholders.issue_invite", new=AsyncMock()) as invite:
        r = await client.post(f"/projects/{slug}/stakeholders",
                              json={"name": "Gary", "email": "not-an-address",
                                    "is_reviewer": True})
    assert r.status_code == 422, r.text
    assert "email" in r.text.lower()
    invite.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_person_already_linked_to_this_project_is_not_invited_again(client, seeded_project_slug):
    """A login is created once, at acceptance - not minted fresh on every later write that
    happens to touch the row. Seeding a users row and a project_memberships row directly
    (rather than going through issue_invite/accept_token, which are exactly what this test
    must stay independent of) reproduces "this person can already log in here" without
    depending on the very call being asserted against."""
    slug = seeded_project_slug
    email = "already@example.com"
    await _purge_system_login(email)  # defensive: a prior failed run may have left this live
    try:
        async with get_system_connection() as conn:
            await insert_user(conn, username=email, email=email, role="reviewer", hashed_pw="x")
            cur = await conn.execute("SELECT id FROM users WHERE username=?", (email,))
            uid = (await cur.fetchone())[0]
            # stakeholder_id is arbitrary here - project_memberships is UNIQUE(user_id,
            # project_slug), so any membership row for this (user, project) is what "already
            # linked" means, independent of which stakeholder record it names.
            await link_membership(conn, user_id=uid, project_slug=slug, stakeholder_id=999999)

        with patch("api.routers.stakeholders.issue_invite", new=AsyncMock()) as invite:
            r = await client.post(f"/projects/{slug}/stakeholders",
                                  json={"name": "Cass", "email": email, "is_reviewer": True})
        assert r.status_code in (200, 201), r.text
        invite.assert_not_awaited()
    finally:
        await _purge_system_login(email)


@pytest.mark.asyncio
async def test_clearing_and_resetting_a_role_after_accepting_does_not_mint_a_second_invite(client, seeded_project_slug):
    """Driven end to end: without the login conjunct, clearing a role back to
    participant-only and then re-setting it reads as "newly set" a second time, and mints a
    second, unused, seven-day-live invite onto a login that can already authenticate - the
    exact shape a stray password-reset credential comes from."""
    slug = seeded_project_slug
    email = "reset@example.com"
    await _purge_system_login(email)  # defensive: a prior failed run may have left this live
    try:
        with patch("api.routers.stakeholders.issue_invite", new=AsyncMock()) as first_invite:
            r = await client.post(f"/projects/{slug}/stakeholders",
                                  json={"name": "Reset", "email": email, "is_reviewer": True})
            assert r.status_code in (200, 201), r.text
            sid = r.json()["id"]
        assert first_invite.await_count == 1

        # Simulate acceptance: a login now exists and is linked to this project's
        # stakeholder - the state accept_token would have produced, without depending on it.
        async with get_system_connection() as conn:
            await insert_user(conn, username=email, email=email, role="reviewer", hashed_pw="x")
            cur = await conn.execute("SELECT id FROM users WHERE username=?", (email,))
            uid = (await cur.fetchone())[0]
            await link_membership(conn, user_id=uid, project_slug=slug, stakeholder_id=sid)

        with patch("api.routers.stakeholders.issue_invite", new=AsyncMock()) as second_invite:
            cleared = await client.patch(f"/projects/{slug}/stakeholders/{sid}",
                                         json={"is_reviewer": False})
            assert cleared.status_code == 200, cleared.text
            assert cleared.json()["is_reviewer"] is False
            reset = await client.patch(f"/projects/{slug}/stakeholders/{sid}",
                                       json={"is_reviewer": True})
            assert reset.status_code == 200, reset.text
            assert reset.json()["is_reviewer"] is True
        second_invite.assert_not_awaited()
    finally:
        await _purge_system_login(email)


@pytest.mark.asyncio
async def test_put_refuses_a_role_reaching_no_email_through_the_effective_state(client, seeded_project_slug):
    """PUT is a full replace of the fields StakeholderIn declares, but is_project_admin and
    is_governor are not among them - so a PUT validated only against its own body, rather
    than against before-state merged with the body, could reach the exact undeliverable shape
    the 422 exists to prevent while never mentioning the role that makes it undeliverable.

    is_governor cannot be set through the API (see
    test_project_admin_and_governor_are_refused_not_silently_ignored), so this seeds it
    directly via insert_stakeholder, matching tests/test_invite_loop.py's own convention for
    states the router cannot produce.
    """
    from api.database import fetch_project, insert_stakeholder

    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        sid = await insert_stakeholder(
            conn, project_id=project["id"], name="Gov", email="gov@example.com",
            is_governor=True,
        )

    with patch("api.routers.stakeholders.issue_invite", new=AsyncMock()) as invite:
        r = await client.put(f"/projects/{SLUG}/stakeholders/{sid}",
                             json={"name": "Gov", "email": ""})
    assert r.status_code == 422, r.text
    assert "email" in r.text.lower()
    invite.assert_not_awaited()


@pytest.mark.asyncio
async def test_patch_with_an_explicit_null_does_not_500_or_clear_the_column(client, seeded_project_slug):
    """Every StakeholderPatch field is optional (X | None) and exclude_unset alone keeps an
    explicit null in the dump - and every one of these columns is NOT NULL. A client clearing
    a form field routinely sends {"field": null} rather than omitting the key; before
    exclude_none, that was an IntegrityError (name, email) or a silent, unintended False
    (is_participant)."""
    slug = seeded_project_slug
    with patch("api.routers.stakeholders.issue_invite", new=AsyncMock()):
        create = await client.post(f"/projects/{slug}/stakeholders",
                                   json={"name": "Null Test", "email": "nulltest@example.com",
                                         "is_participant": True})
        sid = create.json()["id"]

        r = await client.patch(f"/projects/{slug}/stakeholders/{sid}",
                               json={"name": None, "email": None, "is_participant": None,
                                     "job_title": "Updated Title"})
    assert r.status_code == 200, r.text
    body = r.json()
    # Nulled fields are untouched, not cleared and not defaulted to False.
    assert body["name"] == "Null Test"
    assert body["email"] == "nulltest@example.com"
    assert body["is_participant"] is True
    # The one real field in the same request still applies.
    assert body["job_title"] == "Updated Title"


@pytest.mark.asyncio
async def test_project_admin_and_governor_are_refused_not_silently_ignored(client, seeded_project_slug):
    """Before this fix, POST {"is_governor": true} returned 201 with is_governor still
    false - pydantic dropped the undeclared field and nothing told the caller. Neither model
    supports granting these two yet (that needs an authority check this task does not build),
    so the attempt is refused loudly instead of accepted and quietly ignored."""
    slug = seeded_project_slug
    r = await client.post(f"/projects/{slug}/stakeholders",
                          json={"name": "Would-be Governor", "email": "wbg@example.com",
                                "is_governor": True})
    assert r.status_code == 422, r.text
    assert "is_governor" in r.text


@pytest.mark.asyncio
async def test_extra_frontend_fields_still_pass_through_unharmed(client, seeded_project_slug):
    """The models allow (rather than forbid) unknown keys so that interview_status,
    interview_invited_at and interview_completed_at - which ui/src/pages/StakeholderForm.tsx
    sends on every save and which neither model declares - keep working. This is the
    regression the "allow" choice would otherwise open: model_dump() includes allowed extras
    by default, and unpacking them into insert_stakeholder/update_stakeholder as **fields
    would crash on an unknown keyword argument were they not stripped back out before the
    write."""
    slug = seeded_project_slug
    r = await client.post(f"/projects/{slug}/stakeholders",
                          json={"name": "Extra Fields", "email": "extra@example.com",
                                "interview_status": "completed",
                                "interview_invited_at": "2026-01-01T00:00:00Z",
                                "interview_completed_at": "2026-01-02T00:00:00Z"})
    assert r.status_code in (200, 201), r.text


@pytest.mark.asyncio
async def test_resend_invite_reissues_the_live_token(client, seeded_project_slug):
    """The only way today for an operator to recover from a lost or expired invite email -
    issue_invite fires once, on grant, and nothing before this endpoint could ever call it
    again for the same person."""
    slug = seeded_project_slug
    create = await client.post(f"/projects/{slug}/stakeholders",
                               json={"name": "Resend Me", "email": "resend@example.com",
                                     "is_reviewer": True})
    sid = create.json()["id"]

    r = await client.post(f"/projects/{slug}/stakeholders/{sid}/resend-invite")
    assert r.status_code == 200, r.text
    assert "invite_token" in r.json()
    assert r.json()["invite_token"]


@pytest.mark.asyncio
async def test_resend_invite_with_nothing_live_is_404(client, seeded_project_slug):
    slug = seeded_project_slug
    create = await client.post(f"/projects/{slug}/stakeholders",
                               json={"name": "Participant Only", "email": "po@example.com",
                                     "is_participant": True})
    sid = create.json()["id"]

    r = await client.post(f"/projects/{slug}/stakeholders/{sid}/resend-invite")
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_csv_import_cannot_grant_a_role_without_the_invite_guard():
    """import_csv (api/services/stakeholder_service.py) writes via insert_stakeholder /
    update_stakeholder directly, bypassing this router's create_stakeholder /
    update_stakeholder_svc entirely - so today it cannot violate the invariant only because
    its column mapping never mentions a role flag. The obvious next change is adding one, and
    because that change would never touch the router, roles would then be granted with no
    invite and no 422, completely silently.

    This is a trip-wire, not a behavioural test: it fails the moment any _ROLE_FLAGS name
    reaches import_csv's source, forcing whoever adds one to notice and route the write
    through the same guard as the router instead.
    """
    from api.services import stakeholder_service
    from api.routers.stakeholders import _ROLE_FLAGS

    source = inspect.getsource(stakeholder_service.import_csv)
    for flag in _ROLE_FLAGS:
        assert flag not in source, (
            f"{flag} now appears in import_csv - bulk upload can grant a role with no "
            "invite and no 422 unless the write is routed through the same guard as the "
            "router (_validate_deliverable_role / _issue_invite_if_newly_privileged)"
        )
