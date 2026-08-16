"""Granting `project_admin` and `governor`, and what holding `project_admin` then reaches.

Both roles were stored, migrated, walked by `caller_roles`, returned by the API and written
up in CLAUDE.md - and could not be given to anybody, because
`_reject_undeclared_role_flags` 422'd every truthy attempt. sp44 builds the authority check
that refusal was waiting for, and moves the project-configuration doors onto a gate the role
can actually open.

Everything here is driven over HTTP by real, fully-wired logins - users row, membership,
stakeholder row, project - because the recurring failure on this codebase is a test that
verifies a property one layer from where it holds. Two lessons from sp42 shape it
specifically:

  - *Test the chain, not the door.* A unit test on `caller_may_grant_project_roles` would
    pass whether or not any handler consults it, and would say nothing about whether the
    grant it authorises actually reaches the database. Every grant here is asserted on the
    row that comes back, and the escalation questions are driven as whole attacks rather
    than as single refused calls.
  - *Revert conditions separately.* The refusals below are attributed by `detail`, not only
    by status, so a caller refused by two gates at once cannot pass for a witness of either.

The callers, and what each one isolates:

  sysadmin     - the `client` fixture. The built-in env-var administrator, which has **no
                 `users` row at all**; the bootstrap case, and the reason
                 `caller_may_grant_project_roles` reads the platform tier off the token as
                 well as off `users.is_sys_admin`.
  padmin       - is_project_admin on this project, nothing else. Grants, and administers.
  reviewer     - is_reviewer. A content role; no administration, no grant.
  approver     - is_reviewer + is_approver. The most senior *content* caller there is, and
                 still not an administrator - the pair that keeps the two axes apart.
  plain        - a membership and a participant stakeholder. Clears the floor and nothing
                 else.
  org_admin_a  - org_admin of the organisation owning this project. Administers everything,
                 and deliberately may **not** mint a project_admin.
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.auth import create_access_token
from api.config import get_settings
from api.database import (
    fetch_project,
    fetch_stakeholder,
    fetch_user,
    get_connection,
    get_system_connection,
    insert_organisation,
    insert_project_registry,
    insert_stakeholder,
    insert_user,
    link_membership,
)

SLUG = "grantable-roles"
OTHER_SLUG = "grantable-roles-other"

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32

ACCESS_DENIED = "Access denied to this project"
ADMIN_REQUIRED = (
    "Project administration required - org admin or above, or project_admin on this project"
)
PLATFORM_TIER_REQUIRED = "Org admin or above required"
GRANT_REFUSED = "may only be granted by a project_admin on this project"


def _project_body(slug: str) -> dict:
    return {
        "client_slug": slug,
        "llm_mode": "standard",
        "sector": "transport",
        "stakeholder_groups": [],
        "value_stream_labels": [],
        "crews_enabled": ["requirements"],
        "review_gates": True,
        "slack_channel": "",
    }


def _client_for(username: str, role: str, org_id: int | None = None) -> AsyncClient:
    from api.main import app

    token = create_access_token(username, role, "test-secret", org_id=org_id)
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


async def _seed_member(slug: str, *, username: str, **flags) -> int:
    """A login wired the whole way, as `caller_roles` walks it: users row -> membership ->
    stakeholder row on this project -> flags. Returns the stakeholder id."""
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        stakeholder_id = await insert_stakeholder(
            conn, project_id=project["id"], name=username,
            email=f"{username}@example.com", **flags,
        )
    async with get_system_connection() as sys_conn:
        await insert_user(
            sys_conn, username=username, email=f"{username}@example.com",
            role="reviewer", hashed_pw="x",
        )
        user = await fetch_user(sys_conn, username=username)
        await link_membership(
            sys_conn, user_id=user["id"], project_slug=slug, stakeholder_id=stakeholder_id
        )
    return stakeholder_id


async def _stakeholder(slug: str, stakeholder_id: int) -> dict:
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        return await fetch_stakeholder(
            conn, stakeholder_id=stakeholder_id, project_id=project["id"]
        )


@pytest_asyncio.fixture
async def roles(tmp_path, monkeypatch, client):
    """Two projects, six callers, and a plain stakeholder row to grant roles onto.

    DATABASE_DIR and PROJECTS_DIR are redirected at this test's own tmp_path. The shared,
    persistent /tmp/agentpool_test would otherwise carry these fixed usernames between runs,
    which is the failure CLAUDE.md records: passes once, fails on every run afterwards.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()

    for slug in (SLUG, OTHER_SLUG):
        r = await client.post("/projects", json=_project_body(slug))
        assert r.status_code in (200, 201), r.text

    async with get_system_connection() as sys_conn:
        org_a = await insert_organisation(sys_conn, slug="org-grantable", name="Alpha")
        org_b = await insert_organisation(sys_conn, slug="org-grantable-b", name="Beta")
        await insert_project_registry(sys_conn, slug=SLUG, org_id=org_a, display_name=SLUG)
        await insert_project_registry(
            sys_conn, slug=OTHER_SLUG, org_id=org_b, display_name=OTHER_SLUG
        )
        await sys_conn.commit()

    await _seed_member(SLUG, username="gr-padmin", is_project_admin=True)
    await _seed_member(SLUG, username="gr-reviewer", is_reviewer=True)
    await _seed_member(SLUG, username="gr-approver", is_reviewer=True, is_approver=True)
    await _seed_member(SLUG, username="gr-plain", is_participant=True)
    # A project_admin on the *other* engagement, for the cross-project questions.
    await _seed_member(OTHER_SLUG, username="gr-padmin-b", is_project_admin=True)
    # An ordinary row for everyone to try to promote. Not a login - the grant is a write to
    # this row, and whether it can be made is the question, not who ends up holding it.
    target = await _seed_member(SLUG, username="gr-target", is_participant=True)
    # And an outsider account, so "grant a membership" has a target that has none.
    async with get_system_connection() as sys_conn:
        await insert_user(
            sys_conn, username="gr-outsider", email="gr-outsider@example.com",
            role="reviewer", hashed_pw="x",
        )
        await sys_conn.commit()

    padmin = _client_for("gr-padmin", "reviewer")
    padmin_b = _client_for("gr-padmin-b", "reviewer")
    reviewer = _client_for("gr-reviewer", "reviewer")
    approver = _client_for("gr-approver", "reviewer")
    plain = _client_for("gr-plain", "reviewer")
    org_admin_a = _client_for("gr-org-admin-a", "org_admin", org_id=org_a)

    async with padmin, padmin_b, reviewer, approver, plain, org_admin_a:
        yield {
            "sysadmin": client,
            "padmin": padmin,
            "padmin_b": padmin_b,
            "reviewer": reviewer,
            "approver": approver,
            "plain": plain,
            "org_admin_a": org_admin_a,
            "target": target,
        }

    get_settings.cache_clear()


def _refusal(resp) -> tuple[int, str]:
    """Status and refusal reason. A door that let the caller through answers its own payload,
    which has no `detail` - reported as the body rather than raised, so a gate that stops
    refusing fails on the assertion instead of on a TypeError."""
    body = resp.json()
    if isinstance(body, dict) and "detail" in body:
        return resp.status_code, body["detail"]
    return resp.status_code, f"<allowed: {body!r}>"


# ── Part 1: who may grant ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_project_admin_grants_project_admin(roles):
    """The recursion's inductive step, and the whole point of the branch: the role can hand
    itself out. Asserted on the row that comes back, not on the 200 - a grant accepted and
    silently dropped is the exact defect sp37's 422 was built to expose, and it would answer
    200 just as happily."""
    r = await roles["padmin"].patch(
        f"/projects/{SLUG}/stakeholders/{roles['target']}",
        json={"is_project_admin": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_project_admin"] is True
    row = await _stakeholder(SLUG, roles["target"])
    assert row["is_project_admin"] is True, "the response said yes and the database said no"


@pytest.mark.asyncio
async def test_a_project_admin_grants_governor(roles):
    r = await roles["padmin"].patch(
        f"/projects/{SLUG}/stakeholders/{roles['target']}",
        json={"is_governor": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_governor"] is True
    row = await _stakeholder(SLUG, roles["target"])
    assert row["is_governor"] is True


@pytest.mark.asyncio
async def test_the_platform_administrator_grants_on_a_project_it_has_no_row_on(roles):
    """The bootstrap case, and the one a `users`-row fixture cannot see.

    A fresh project has no stakeholders, so nobody the walk can reach holds project_admin;
    the operator has to be able to appoint the first one or the recursion never starts. The
    `client` fixture is the built-in ADMIN_USERNAME administrator, which has **no users row
    at all** - `POST /auth/token` matches the environment before it looks at the table. A
    test that seeded a users row with is_sys_admin=1 would prove the database implication
    and miss that production cannot bootstrap.
    """
    async with get_system_connection() as sys_conn:
        assert await fetch_user(sys_conn, username="admin") is None, (
            "the bootstrap caller is supposed to have no users row - this test is void if it has"
        )

    r = await roles["sysadmin"].patch(
        f"/projects/{SLUG}/stakeholders/{roles['target']}",
        json={"is_project_admin": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_project_admin"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("caller", ["reviewer", "approver", "plain"])
@pytest.mark.parametrize("flag", ["is_project_admin", "is_governor"])
async def test_a_caller_without_project_admin_cannot_grant_either_role(roles, caller, flag):
    """The refusals, one caller at a time so each is its own witness.

    `approver` matters most: it is the most senior *content* role on the project, and the
    two axes must stay apart. `plain` and `reviewer` are refused a step earlier, by the
    administration gate on the door - which is why the detail is asserted rather than the
    status. All three would answer 403 whatever refused them.
    """
    r = await roles[caller].patch(
        f"/projects/{SLUG}/stakeholders/{roles['target']}", json={flag: True}
    )
    assert _refusal(r) == (403, ADMIN_REQUIRED)
    row = await _stakeholder(SLUG, roles["target"])
    assert row[flag] is False, "refused, and granted anyway"


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["is_project_admin", "is_governor"])
async def test_an_org_admin_administers_the_project_but_cannot_mint_these_roles(roles, flag):
    """The one caller that reaches the *door* and is still refused the *grant*.

    This is the test that distinguishes the two checks. An org_admin clears
    `require_project_administration` on its login tier alone, so the refusal here can only
    come from `_assert_may_grant_role_flags` - and its distinct sentence proves it did. Drop
    that guard and this passes with a 200; drop the door's gate instead and it still refuses,
    with the other sentence.
    """
    r = await roles["org_admin_a"].patch(
        f"/projects/{SLUG}/stakeholders/{roles['target']}", json={flag: True}
    )
    status, detail = _refusal(r)
    assert status == 403, r.text
    assert GRANT_REFUSED in detail, detail
    assert flag in detail, "the refusal must name what it refused"
    row = await _stakeholder(SLUG, roles["target"])
    assert row[flag] is False


@pytest.mark.asyncio
async def test_the_org_admin_really_can_administer_this_project(roles):
    """The control for the test above. Without it, an org_admin refused for some unrelated
    reason - no membership, wrong organisation - would satisfy it silently."""
    r = await roles["org_admin_a"].patch(
        f"/projects/{SLUG}/stakeholders/{roles['target']}", json={"job_title": "Head of Ops"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["job_title"] == "Head of Ops"


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["is_project_admin", "is_governor"])
async def test_revocation_still_needs_no_authority_check(roles, flag):
    """The asymmetry sp37's review round 2 required, kept deliberately.

    Revocation is the safe direction, and it is the repair for a row holding a role with no
    deliverable address - which `_validate_deliverable_role` would otherwise refuse to touch.
    An org_admin cannot grant the flag (above) and must still be able to take it away.
    """
    granted = await roles["padmin"].patch(
        f"/projects/{SLUG}/stakeholders/{roles['target']}", json={flag: True}
    )
    assert granted.json()[flag] is True, "precondition"

    r = await roles["org_admin_a"].patch(
        f"/projects/{SLUG}/stakeholders/{roles['target']}", json={flag: False}
    )
    assert r.status_code == 200, r.text
    assert r.json()[flag] is False
    row = await _stakeholder(SLUG, roles["target"])
    assert row[flag] is False, "the response said cleared and the database disagreed"


@pytest.mark.asyncio
async def test_creating_a_stakeholder_with_a_role_is_gated_the_same_way(roles):
    """POST, not only PATCH. A guard wired on the update path alone leaves the create path
    as the way round it, which is the shape of every hole this codebase has closed."""
    body = {"name": "Fresh Governor", "email": "freshgov@example.com", "is_governor": True}

    refused = await roles["org_admin_a"].post(f"/projects/{SLUG}/stakeholders", json=body)
    status, detail = _refusal(refused)
    assert status == 403, refused.text
    assert GRANT_REFUSED in detail

    allowed = await roles["padmin"].post(f"/projects/{SLUG}/stakeholders", json=body)
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["is_governor"] is True


@pytest.mark.asyncio
async def test_the_csv_import_is_not_a_way_round_the_grant_check(roles):
    """The other write door into `stakeholders`, and the one an authority check on the JSON
    body cannot see.

    `import_csv` builds an explicit field whitelist and no role flag is on it, so a column
    named `is_project_admin` is simply ignored - the guard is unreachable rather than
    bypassed. That is the right answer, but it is a property of a list in
    `stakeholder_service.py` that nothing else asserts, and adding role columns to a CSV
    importer is an obvious future request. Pinned here so that change has to be a deliberate
    one that comes past this test.
    """
    csv_body = (
        "name,email,is_project_admin,is_governor\n"
        "Sneaky Import,sneaky@example.com,true,true\n"
    )
    r = await roles["org_admin_a"].post(
        f"/projects/{SLUG}/stakeholders/import",
        files={"file": ("people.csv", csv_body.encode(), "text/csv")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1, r.text

    async with get_connection(SLUG) as conn:
        cur = await conn.execute(
            "SELECT is_project_admin, is_governor FROM stakeholders WHERE email=?",
            ("sneaky@example.com",),
        )
        row = await cur.fetchone()
    assert row is not None, "the import did not run - this test proves nothing as written"
    assert not row["is_project_admin"], "the CSV importer granted project_admin"
    assert not row["is_governor"], "the CSV importer granted governor"


@pytest.mark.asyncio
async def test_my_permissions_reports_the_grant_right_the_door_enforces(roles):
    """What the UI asks before rendering the two checkboxes. A checkbox that always refuses
    is worse than no checkbox, so the report and the door must not disagree - and both read
    `caller_may_grant_project_roles`, rather than the UI trusting a second copy of the rule.
    """
    assert (await roles["padmin"].get(f"/projects/{SLUG}/my-permissions")).json()[
        "can_grant_roles"
    ] is True
    assert (await roles["approver"].get(f"/projects/{SLUG}/my-permissions")).json()[
        "can_grant_roles"
    ] is False
    assert (await roles["org_admin_a"].get(f"/projects/{SLUG}/my-permissions")).json()[
        "can_grant_roles"
    ] is False


# ── Part 2: what project_admin now reaches ────────────────────────────────────
#
# `padmin` is an org_admin of nothing. Its login role is "reviewer" - the role every accepted
# invite mints - so it clears no platform-tier dependency anywhere. Every success below is
# `require_project_administration`'s per-project arm and nothing else.


@pytest.mark.asyncio
async def test_the_project_admin_holds_no_platform_tier(roles):
    """The control the whole of Part 2 rests on. If this caller were an org_admin by
    accident, every success below would be sp38's gate passing and would say nothing about
    project_admin at all. `/auth/users` is org-admin-or-above and carries no slug."""
    assert (await roles["padmin"].get("/auth/users")).status_code == 403


@pytest.mark.asyncio
async def test_a_project_admin_may_write_the_milestone_schedule(roles):
    padmin = roles["padmin"]
    assert (await padmin.post(f"/projects/{SLUG}/milestones/seed")).status_code == 200

    created = await padmin.post(
        f"/projects/{SLUG}/milestones", json={"title": "Handover", "due_date": "2026-10-01"}
    )
    assert created.status_code in (200, 201), created.text
    new_id = created.json()["id"]
    assert (await padmin.patch(
        f"/projects/{SLUG}/milestones/{new_id}", json={"title": "Handover (revised)"}
    )).status_code == 200
    assert (await padmin.delete(f"/projects/{SLUG}/milestones/{new_id}")).status_code == 204


@pytest.mark.asyncio
async def test_a_project_admin_may_write_the_project_calendar(roles):
    padmin = roles["padmin"]
    body = {"label": "Shutdown", "start_date": "2026-12-24", "end_date": "2027-01-02"}
    made = await padmin.post(f"/projects/{SLUG}/nonworking", json=body)
    assert made.status_code == 201, made.text
    range_id = made.json()["id"]
    assert (await padmin.patch(
        f"/projects/{SLUG}/nonworking/{range_id}", json={**body, "label": "Works shutdown"}
    )).status_code == 200
    assert (await padmin.delete(f"/projects/{SLUG}/nonworking/{range_id}")).status_code == 204


@pytest.mark.asyncio
async def test_a_project_admin_may_configure_the_project_and_its_branding(roles):
    padmin = roles["padmin"]
    settings = await padmin.get(f"/projects/{SLUG}/settings")
    assert settings.status_code == 200, settings.text

    patched = await padmin.patch(
        f"/projects/{SLUG}/settings", json={**settings.json(), "sector": "utilities"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["sector"] == "utilities"

    uploaded = await padmin.post(
        f"/projects/{SLUG}/branding/image",
        files={"file": ("header.png", PNG, "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text


@pytest.mark.asyncio
async def test_a_project_admin_may_administer_this_projects_people(roles):
    padmin = roles["padmin"]
    created = await padmin.post(
        f"/projects/{SLUG}/stakeholders",
        json={"name": "New Person", "email": "newperson@example.com"},
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    assert (await padmin.patch(
        f"/projects/{SLUG}/stakeholders/{sid}", json={"job_title": "Analyst"}
    )).status_code == 200
    assert (await padmin.delete(f"/projects/{SLUG}/stakeholders/{sid}")).status_code == 204


@pytest.mark.asyncio
@pytest.mark.parametrize("caller", ["reviewer", "approver", "plain"])
async def test_the_widened_doors_still_refuse_everyone_else(roles, caller):
    """Widening is not opening. These three hold every content role there is between them
    and still configure nothing - the two axes are the same distance apart as before."""
    calls = [
        roles[caller].post(f"/projects/{SLUG}/milestones", json={"title": "Sneak"}),
        roles[caller].post(
            f"/projects/{SLUG}/nonworking",
            json={"label": "X", "start_date": "2026-12-24", "end_date": "2027-01-02"},
        ),
        roles[caller].patch(f"/projects/{SLUG}/settings", json={"sector": "sneak"}),
        roles[caller].post(
            f"/projects/{SLUG}/stakeholders", json={"name": "Sneak", "email": "s@example.com"}
        ),
    ]
    for call in calls:
        assert _refusal(await call) == (403, ADMIN_REQUIRED)


# ── Part 3: can a project_admin escalate? ─────────────────────────────────────
#
# They can appoint other project_admins on their own project, so the question is what that
# reaches. Two boundaries have to hold: the project boundary, and the account boundary. Both
# are driven as whole attacks rather than as single refused calls - sp42's lesson, where
# scoping a membership write was not enough because claiming an outsider *for your own
# organisation* was itself a write to your own organisation.


@pytest.mark.asyncio
async def test_a_project_admin_cannot_reach_another_engagement(roles):
    """The project boundary. `check_project_access` runs first and this caller has no
    membership on the other slug, so the refusal is the floor's - which is the point: a
    per-project role is bounded by the membership that carries it."""
    padmin = roles["padmin"]
    calls = [
        padmin.get(f"/projects/{OTHER_SLUG}/stakeholders"),
        padmin.post(
            f"/projects/{OTHER_SLUG}/stakeholders",
            json={"name": "Reach", "email": "reach@example.com", "is_project_admin": True},
        ),
        padmin.post(f"/projects/{OTHER_SLUG}/milestones", json={"title": "Reach"}),
        padmin.patch(f"/projects/{OTHER_SLUG}/settings", json={"sector": "reach"}),
    ]
    for call in calls:
        assert _refusal(await call) == (403, ACCESS_DENIED)


@pytest.mark.asyncio
async def test_a_project_admin_cannot_manufacture_the_membership_that_would_widen_them(roles):
    """The escalation sp38 and sp42 each closed, attempted from the new role.

    `POST /auth/users/{id}/projects/{slug}` writes the `project_memberships` row every
    `check_project_access` reads - a gate that reads a table is worth nothing if a caller can
    write themselves into it. It is on the platform tier and deliberately did not widen in
    sp44, so a project_admin cannot grant itself a foothold on the other engagement and then
    walk in as a legitimate member. Asserted on the row, then on the door it would have
    opened.
    """
    async with get_system_connection() as sys_conn:
        me = await fetch_user(sys_conn, username="gr-padmin")
        outsider = await fetch_user(sys_conn, username="gr-outsider")

    # The attack shaped as it would actually be run, which is the sp42 lesson: the
    # cross-project call below is refused by the membership floor whether or not this door
    # widened, so on its own it witnesses nothing about the door. The write a project_admin
    # *could* reach is a membership on their **own** slug - handing an arbitrary account the
    # read access `check_project_access` grants - and that is the one asserted on the row.
    own = await roles["padmin"].post(f"/auth/users/{outsider['id']}/projects/{SLUG}")
    assert _refusal(own) == (403, PLATFORM_TIER_REQUIRED)

    async def _membership(user_id: int, slug: str) -> bool:
        async with get_system_connection() as sys_conn:
            cur = await sys_conn.execute(
                "SELECT 1 FROM project_memberships WHERE user_id=? AND project_slug=?",
                (user_id, slug),
            )
            return await cur.fetchone() is not None

    assert not await _membership(outsider["id"], SLUG), (
        "a project_admin manufactured a membership - the refusal is decoration"
    )
    async with _client_for("gr-outsider", "reviewer") as outsider_client:
        assert _refusal(
            await outsider_client.get(f"/projects/{SLUG}/stakeholders")
        ) == (403, ACCESS_DENIED)

    # And the same door aimed at the other engagement, for the boundary itself.
    resp = await roles["padmin"].post(f"/auth/users/{me['id']}/projects/{OTHER_SLUG}")
    assert resp.status_code == 403, resp.text
    assert not await _membership(me["id"], OTHER_SLUG)
    assert _refusal(
        await roles["padmin"].get(f"/projects/{OTHER_SLUG}/stakeholders")
    ) == (403, ACCESS_DENIED)


@pytest.mark.asyncio
async def test_a_project_admin_cannot_touch_an_account(roles):
    """The account boundary. The platform tier lives in `users.role`, and every door that
    writes it is account administration - `_assert_may_administer`'s family, which sp44 did
    not widen. A project_admin cannot create a login, promote one, or take one over."""
    padmin = roles["padmin"]
    async with get_system_connection() as sys_conn:
        outsider = await fetch_user(sys_conn, username="gr-outsider")

    calls = [
        padmin.get("/auth/users"),
        padmin.post("/auth/users", json={
            "username": "climber", "email": "climber@example.com",
            "password": "secret123", "role": "sysadmin",
        }),
        padmin.patch(f"/auth/users/{outsider['id']}", json={
            "email": "gr-outsider@example.com", "role": "sysadmin",
        }),
        padmin.post(f"/auth/users/{outsider['id']}/reset-link"),
        padmin.delete(f"/auth/users/{outsider['id']}"),
    ]
    for call in calls:
        status, _ = _refusal(await call)
        assert status == 403, "an account door answered a project_admin"

    async with get_system_connection() as sys_conn:
        assert await fetch_user(sys_conn, username="climber") is None
        still = await fetch_user(sys_conn, username="gr-outsider")
    assert still is not None, "the account was deleted anyway"
    assert still["role"] == "reviewer", "the account was promoted anyway"


@pytest.mark.asyncio
async def test_the_logins_a_project_admin_can_cause_are_confined_to_this_project(roles):
    """The account boundary's other side, and the one that is genuinely new in sp44.

    Stakeholder administration issues an invite the moment a role beyond participant is set
    on somebody with an address, and accepting one creates a `users` row. That door was
    consultant-only before this branch, so a client-side project_admin causing a login to
    exist is a new capability and worth pinning rather than assuming.

    What confines it: `accept_token` hard-codes `role="reviewer"` - load-bearing, per its own
    comment, because `check_project_access` only attempts the membership lookup for that
    value - and the membership it creates names this project alone. So the account a
    project_admin can cause reaches exactly the engagement they already administer.
    """
    from unittest.mock import AsyncMock, patch

    with patch("api.routers.stakeholders.issue_invite", new=AsyncMock()) as invite:
        created = await roles["padmin"].post(
            f"/projects/{SLUG}/stakeholders",
            json={"name": "Invitee", "email": "invitee@example.com", "is_reviewer": True},
        )
    assert created.status_code == 201, created.text
    invite.assert_awaited_once()
    assert invite.await_args.kwargs["project_slug"] == SLUG, (
        "the invite a project_admin caused named an engagement other than their own"
    )

    # Nothing in that request could have carried a platform role: the invite path chooses it,
    # and the stakeholder models have no field for it.
    assert "role" not in invite.await_args.kwargs


@pytest.mark.asyncio
async def test_the_role_itself_confers_no_content_authority(roles):
    """The axis that did not move. Holding project_admin is not approval: it contributes
    nothing to `caller_may_contribute` or `caller_may_approve`, which read `{reviewer,
    approver}` and `{approver}` and are stated once in `authority_service.py`.

    Asked of the walk directly rather than through a door, deliberately - the property is
    about what the walk answers, and every content gate is written in terms of that answer.
    """
    from api.services.authority_service import (
        caller_may_approve,
        caller_may_contribute,
        caller_roles,
    )

    payload = {"sub": "gr-padmin", "role": "reviewer"}
    assert await caller_roles(SLUG, payload) == {"project_admin"}
    assert await caller_may_contribute(SLUG, payload) is False
    assert await caller_may_approve(SLUG, payload) is False


@pytest.mark.asyncio
async def test_a_project_admin_can_promote_themselves_to_approver_on_their_own_project(roles):
    """**A known consequence, recorded rather than discovered later.**

    The test above is about the role. This is about the *door*: setting `is_approver` is
    stakeholder administration, and stakeholder administration is one of the sixteen doors
    that widened. So a project_admin can PATCH their own stakeholder row and hold content
    authority a moment later. Administration mints content on this codebase - it always did,
    since an org_admin could set `is_approver` on a row linked to their own login - and sp44
    extends who can do it from the consultant to the client's own project administrator.

    That is a real widening and it should be a decision, not a surprise. Asserting it here
    means changing it has to change this test, and leaving it means nobody rediscovers it
    from a live engagement. What bounds it is the project: the promotion is a write to a
    stakeholder row on this slug, `caller_roles` keys the lookup on the membership for this
    slug, and `test_a_project_admin_cannot_reach_another_engagement` covers the other side.
    """
    from api.services.authority_service import caller_may_approve

    payload = {"sub": "gr-padmin", "role": "reviewer"}
    assert await caller_may_approve(SLUG, payload) is False, "precondition"

    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        cur = await conn.execute(
            "SELECT id FROM stakeholders WHERE project_id=? AND name='gr-padmin'",
            (project["id"],),
        )
        own_row = (await cur.fetchone())["id"]

    r = await roles["padmin"].patch(
        f"/projects/{SLUG}/stakeholders/{own_row}", json={"is_approver": True}
    )
    assert r.status_code == 200, r.text
    assert await caller_may_approve(SLUG, payload) is True, (
        "if this now refuses, the self-promotion route has been closed - which is a "
        "welcome change, and this test is the place to say so"
    )

    # And it stops at the project line. The promotion bought nothing next door.
    assert await caller_may_approve(OTHER_SLUG, payload) is False


@pytest.mark.asyncio
async def test_a_project_admin_of_another_project_grants_nothing_here(roles):
    """`caller_may_grant_project_roles` takes the slug for a reason. A role held on one
    engagement must not answer a question asked about another - the walk keys the stakeholder
    lookup on the membership for *this* slug, and this is that property driven over HTTP."""
    r = await roles["padmin_b"].patch(
        f"/projects/{SLUG}/stakeholders/{roles['target']}",
        json={"is_project_admin": True},
    )
    assert _refusal(r) == (403, ACCESS_DENIED)
    row = await _stakeholder(SLUG, roles["target"])
    assert row["is_project_admin"] is False


# ── The governor role, honestly scoped ────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_governor_receives_pams_report(roles):
    """The one thing `governor` does. Notification routing filters on the flag columns, and
    `is_governor` joined that tuple in sp44 - which was decoration until the flag could be
    set on anybody, and is the reason this test is driven from a real granted row rather
    than from a hand-built list of dicts.
    """
    from api.database import fetch_stakeholders
    from api.services.pam_report_job import resolve_recipients

    granted = await roles["padmin"].patch(
        f"/projects/{SLUG}/stakeholders/{roles['target']}", json={"is_governor": True}
    )
    assert granted.json()["is_governor"] is True, "precondition"

    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        stakeholders = await fetch_stakeholders(conn, project_id=project["id"])

    _, intended = resolve_recipients(stakeholders, dev_mode=False)
    assert "gr-target@example.com" in intended, (
        "a governor was granted and PAM's report still does not reach them"
    )


@pytest.mark.asyncio
async def test_the_governor_role_gates_nothing_else(roles):
    """Stated as a test rather than only in prose, so it fails the day it stops being true.

    The design also says governors "complete" milestones. There is no distinct
    milestone-completion action in the code - `rebaseline` is the nearest and is content-
    gated on `approver` - so sp44 deliberately invented none, and a governor configures
    nothing and approves nothing. Sub-project C owns that question along with the schedule.
    """
    from api.services.authority_service import (
        caller_may_administer_project,
        caller_may_approve,
        caller_may_contribute,
        caller_may_grant_project_roles,
    )

    await _seed_member(SLUG, username="gr-governor", is_governor=True)
    payload = {"sub": "gr-governor", "role": "reviewer"}

    assert await caller_may_administer_project(SLUG, payload) is False
    assert await caller_may_grant_project_roles(SLUG, payload) is False
    assert await caller_may_contribute(SLUG, payload) is False
    assert await caller_may_approve(SLUG, payload) is False

    async with _client_for("gr-governor", "reviewer") as governor:
        assert _refusal(
            await governor.post(f"/projects/{SLUG}/milestones", json={"title": "Complete"})
        ) == (403, ADMIN_REQUIRED)
