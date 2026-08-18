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


def _anon() -> AsyncClient:
    """A client with no Authorization header at all - `/auth/accept` takes none, which is
    exactly what makes an invite token a credential rather than a convenience."""
    from api.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _live_invite_token(email: str) -> str | None:
    """The raw token of the live invite issued to this address, read from the database.

    The tests below need to redeem a real invite without going through the resend door - that
    door is the thing under test. `auth_tokens` stores a hash, not the raw token, so the raw
    value is not recoverable from it; `issue_invite` is patched to capture it instead, in the
    one place where capturing it is not itself the attack.
    """
    return _ISSUED_TOKENS.get(email.strip().lower())


_ISSUED_TOKENS: dict[str, str] = {}


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

    # The real issue_invite, wrapped so the raw token it returns is recoverable. Not a mock:
    # the invite is genuinely issued and genuinely redeemable, which is what the chains below
    # need. `auth_tokens` stores only a hash, so without this there is no way to redeem an
    # invite except through the resend door - and that door is the thing under test.
    import api.routers.stakeholders as stakeholders_router
    from api.services.invite_service import issue_invite as _real_issue_invite

    _ISSUED_TOKENS.clear()

    async def _capturing_issue_invite(*, email: str, project_slug: str, stakeholder_id: int):
        raw = await _real_issue_invite(
            email=email, project_slug=project_slug, stakeholder_id=stakeholder_id
        )
        _ISSUED_TOKENS[email.strip().lower()] = raw
        return raw

    monkeypatch.setattr(stakeholders_router, "issue_invite", _capturing_issue_invite)

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
    refusing fails on the assertion instead of on an exception.

    The bodyless case is not hypothetical tidiness: `DELETE /stakeholders/{id}` answers 204
    with an empty body, so a `resp.json()` here raised JSONDecodeError the moment its gate was
    removed. The test still failed, but on a decoder error rather than on the sentence saying
    a member had just deleted a colleague - which is the difference between a power-check that
    reads as a witness and one that reads as a broken test.
    """
    try:
        body = resp.json()
    except ValueError:
        return resp.status_code, f"<allowed: {resp.status_code}, empty body>"
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
    at all** - `POST /auth/login` matches the environment before it looks at the table. A
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
async def test_a_project_admin_may_map_this_projects_people_to_the_value_chain(roles):
    """`POST /{slug}/assignment`. The door was org-admin-or-above while the page that wrote
    it was gated behind an orchestration run; the surface is Jordan's Setup tab now, and the
    person who adds the stakeholders is the person who says which activities they speak for.

    Asserted on the effect as well as the status, because a 200 from a handler that stored
    nothing is exactly the shape this branch is fixing.
    """
    padmin = roles["padmin"]
    saved = await padmin.post(
        f"/projects/{SLUG}/assignment",
        json=[{"stakeholder_id": roles["target"], "node_id": "1.2"}],
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["saved"] == 1

    read_back = await padmin.get(f"/projects/{SLUG}/assignment")
    assert [
        (a["stakeholder_id"], a["node_id"]) for a in read_back.json()["assignments"]
    ] == [(roles["target"], "1.2")]


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


# ── One test per widened door, each witnessing its own gate ───────────────────
#
# The test above drives four doors in one function, which is exactly how five of the seven
# gates on `stakeholders.py` went unwitnessed: reverting them *together* left `create` and
# `patch` to do the refusing, and the suite stayed green with `import`, `PUT`, `DELETE` and
# `PUT /stakeholder-assignments` wide open. Reverted one at a time, four of them produced
# **zero** failures across all 1652 tests.
#
# That is the sp42 lesson in its exact shape - a neighbour doing the refusing - so each door
# below gets its own test, driven by `plain`: a real member holding `is_participant` and
# nothing else, which is what an interviewee who accepted an invite looks like. Each asserts
# the *effect* as well as the refusal, because with the gate gone `check_project_access` is
# the only authority left and every one of these is a write.


@pytest.mark.asyncio
async def test_a_member_cannot_import_a_stakeholder_csv(roles):
    """`POST /{slug}/stakeholders/import`. With its gate gone, any member could bulk-insert
    arbitrary people into the engagement."""
    csv_body = "name,email\nUninvited Guest,guest@evil.test\n"

    r = await roles["plain"].post(
        f"/projects/{SLUG}/stakeholders/import",
        files={"file": ("people.csv", csv_body.encode(), "text/csv")},
    )

    assert _refusal(r) == (403, ADMIN_REQUIRED)
    async with get_connection(SLUG) as conn:
        cur = await conn.execute(
            "SELECT 1 FROM stakeholders WHERE email=?", ("guest@evil.test",)
        )
        assert await cur.fetchone() is None, "the import ran anyway - the refusal is decoration"


@pytest.mark.asyncio
async def test_a_member_cannot_full_replace_a_stakeholder(roles):
    """`PUT /{slug}/stakeholders/{id}`. A full replace is also the reassignment door: changing
    the email is a change of person, which revokes the previous holder's membership and
    invites the new address. With its gate gone a member could point somebody else's row at
    an address they control."""
    target = roles["target"]
    before = await _stakeholder(SLUG, target)

    r = await roles["plain"].put(
        f"/projects/{SLUG}/stakeholders/{target}",
        json={"name": "Seized", "email": "seized@evil.test", "is_reviewer": True},
    )

    assert _refusal(r) == (403, ADMIN_REQUIRED)
    after = await _stakeholder(SLUG, target)
    assert after["email"] == before["email"], "the row was re-pointed at another person"
    assert after["name"] == before["name"]
    assert after["is_reviewer"] == before["is_reviewer"]


@pytest.mark.asyncio
async def test_a_member_cannot_delete_a_stakeholder(roles):
    """`DELETE /{slug}/stakeholders/{id}`. The sharpest of the four, because the handler also
    calls `_revoke_membership` - so with its gate gone a member could cut any colleague's
    login out of the engagement, `project_memberships` row and all. The membership is what is
    asserted, not only the stakeholder row."""
    async with get_system_connection() as sys_conn:
        victim = await fetch_user(sys_conn, username="gr-reviewer")

    async def _has_membership() -> bool:
        async with get_system_connection() as sys_conn:
            cur = await sys_conn.execute(
                "SELECT 1 FROM project_memberships WHERE user_id=? AND project_slug=?",
                (victim["id"], SLUG),
            )
            return await cur.fetchone() is not None

    assert await _has_membership(), "precondition: the victim is really in the project"
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        cur = await conn.execute(
            "SELECT id FROM stakeholders WHERE project_id=? AND name='gr-reviewer'",
            (project["id"],),
        )
        victim_row = (await cur.fetchone())["id"]

    r = await roles["plain"].delete(f"/projects/{SLUG}/stakeholders/{victim_row}")

    assert _refusal(r) == (403, ADMIN_REQUIRED)
    assert await _stakeholder(SLUG, victim_row) is not None, "the row was deleted anyway"
    assert await _has_membership(), (
        "the membership was revoked anyway - a member cut another member out of the project"
    )
    # And the victim can still reach the engagement, which is the thing the row protects.
    async with _client_for("gr-reviewer", "reviewer") as victim_client:
        assert (await victim_client.get(f"/projects/{SLUG}/milestones")).status_code == 200


@pytest.mark.asyncio
async def test_a_member_cannot_rewrite_the_node_assignments(roles):
    """`POST /{slug}/assignment`. A full replace of who is assigned to which value chain
    node - which is what the Interview Coordinator plans sessions from, so rewriting it
    redirects the interview programme.

    This used to drive `PUT /{slug}/stakeholder-assignments`, which wrote the second,
    unread assignment table. Both are retired; the mapping has one door now, and the gate
    moved with it rather than being dropped.
    """
    from api.database import (
        fetch_stakeholder_assignments,
        replace_stakeholder_assignments,
    )

    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        await replace_stakeholder_assignments(
            conn,
            project_id=project["id"],
            assignments=[{"stakeholder_id": roles["target"], "node_id": "1.2"}],
        )
        before = await fetch_stakeholder_assignments(conn, project_id=project["id"])
    assert before, "precondition: there is an assignment to overwrite"

    r = await roles["plain"].post(f"/projects/{SLUG}/assignment", json=[])

    assert _refusal(r) == (403, ADMIN_REQUIRED)
    async with get_connection(SLUG) as conn:
        after = await fetch_stakeholder_assignments(conn, project_id=project["id"])
    assert after == before, "the assignments were replaced anyway"


@pytest.mark.asyncio
async def test_a_member_cannot_create_a_stakeholder(roles):
    """`POST /{slug}/stakeholders`, with its own effect assertion rather than only the shared
    parametrised refusal above."""
    r = await roles["plain"].post(
        f"/projects/{SLUG}/stakeholders",
        json={"name": "Uninvited", "email": "uninvited@evil.test"},
    )
    assert _refusal(r) == (403, ADMIN_REQUIRED)
    async with get_connection(SLUG) as conn:
        cur = await conn.execute(
            "SELECT 1 FROM stakeholders WHERE email=?", ("uninvited@evil.test",)
        )
        assert await cur.fetchone() is None


@pytest.mark.asyncio
async def test_a_member_cannot_patch_a_stakeholder(roles):
    """`PATCH /{slug}/stakeholders/{id}`. The partial-update door, and the one a member would
    reach for to give themselves a role."""
    target = roles["target"]

    r = await roles["plain"].patch(
        f"/projects/{SLUG}/stakeholders/{target}", json={"is_approver": True}
    )

    assert _refusal(r) == (403, ADMIN_REQUIRED)
    assert (await _stakeholder(SLUG, target))["is_approver"] is False


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


# ── The resend-invite door, and the two chains it would have opened ───────────
#
# `POST .../resend-invite` returns a raw, redeemable invite token, and `POST /auth/accept`
# takes no authentication. sp44 briefly widened this door with the rest of the router; it is
# back on the platform tier, because it is a credential factory rather than configuration.
#
# Both chains below are driven end to end. Each first shows the mechanism working for a
# caller who is *meant* to have it, so the refusal that follows is a refusal of something
# real - a test that only asserted a 403 could not tell a closed hole from a broken feature.


@pytest.mark.asyncio
async def test_resend_invite_is_platform_tier_not_project_administration(roles):
    """The gate itself. `padmin` administers everything else on this project and is refused
    here, with the *platform tier's* sentence - which is what says this door did not widen
    rather than that some other guard happened to refuse."""
    created = await roles["padmin"].post(
        f"/projects/{SLUG}/stakeholders",
        json={"name": "Ghost", "email": "ghost@evil.test", "is_reviewer": True},
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]

    for caller in ("padmin", "approver", "reviewer", "plain"):
        assert _refusal(
            await roles[caller].post(f"/projects/{SLUG}/stakeholders/{sid}/resend-invite")
        ) == (403, PLATFORM_TIER_REQUIRED)

    # The control: it is a working door, not a dead one.
    allowed = await roles["org_admin_a"].post(
        f"/projects/{SLUG}/stakeholders/{sid}/resend-invite"
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["invite_token"], "the door returns a token to whoever may open it"


@pytest.mark.asyncio
async def test_my_permissions_reports_the_invite_link_right_the_door_enforces(roles):
    """What the stakeholder list asks before offering "issue an invite link".

    The report and the door are driven together, per caller, in one test: a button offered
    to somebody the door 403s is worse than no button, and a report that quietly widened
    while the door held would be invisible to a test that only asked one of them. Both read
    `is_org_admin_or_above`, so this is one rule observed from two sides rather than a
    second copy of it.

    Note which way round it goes: `padmin` administers everything else on this engagement
    and is refused here, while `org_admin_a` - who may not even mint a project_admin - is
    allowed. This is the one permission on the endpoint that is narrower than administering
    the project.
    """
    created = await roles["org_admin_a"].post(
        f"/projects/{SLUG}/stakeholders",
        json={"name": "Link Target", "email": "link-target@example.com", "is_reviewer": True},
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]

    for caller, may in (
        ("padmin", False),
        ("approver", False),
        ("reviewer", False),
        ("plain", False),
        ("org_admin_a", True),
    ):
        reported = (await roles[caller].get(f"/projects/{SLUG}/my-permissions")).json()
        assert reported["can_issue_invite_links"] is may, (
            f"/my-permissions tells {caller} the wrong thing about the resend door"
        )
        opened = await roles[caller].post(
            f"/projects/{SLUG}/stakeholders/{sid}/resend-invite"
        )
        if may:
            assert opened.status_code == 200, opened.text
            assert opened.json()["invite_token"], "reported as permitted, and hands nothing back"
        else:
            assert _refusal(opened) == (403, PLATFORM_TIER_REQUIRED), (
                f"{caller} is told no and let through anyway"
            )


@pytest.mark.asyncio
async def test_chain_a_a_project_admin_cannot_mint_a_login_it_controls(roles):
    """Chain A: create a stakeholder for an address you own, resend, redeem, hold a session.

    Every step but the resend is legitimately available to a project_admin, and should be -
    they administer this project's people. The resend is the only step that hands them a
    credential, so it is the only step that has to refuse. Asserted on the `users` row, not
    on the status code: the question is whether an account they control comes into being.
    """
    created = await roles["padmin"].post(
        f"/projects/{SLUG}/stakeholders",
        json={"name": "Ghost", "email": "ghost@evil.test", "is_reviewer": True},
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]

    resend = await roles["padmin"].post(f"/projects/{SLUG}/stakeholders/{sid}/resend-invite")

    assert _refusal(resend) == (403, PLATFORM_TIER_REQUIRED)
    assert "invite_token" not in resend.text, "the token leaked in the refusal body"

    # The invite really was issued by the create above - so the only thing standing between
    # this caller and a login is their inability to retrieve it.
    assert _live_invite_token("ghost@evil.test") is not None, (
        "no invite exists, so this test would pass even with the resend door wide open"
    )
    async with get_system_connection() as sys_conn:
        assert await fetch_user(sys_conn, username="ghost@evil.test") is None, (
            "an account the project_admin controls came into being"
        )


@pytest.mark.asyncio
async def test_chain_b_the_pre_registration_chain_across_a_project_boundary(roles):
    """Chain B, the one that crosses the boundary using only correctly-behaving doors.

    The attacker pre-registers an account for a *real* person who has no login yet, choosing
    the password. Later, a consultant invites that person onto a **different** engagement.
    The victim redeems it. `accept_token` behaves correctly throughout - it refuses to touch
    the existing password, and it mints no session - **and still writes the
    `project_memberships` row**, because for a known email an invite is a membership grant
    rather than an authentication event. The attacker, holding that password, now reads the
    second engagement.

    This is driven in full, in two halves. First the mechanism, with the platform-tier caller
    who may legitimately resend - proving the chain is real and that the severity claim in
    `resend_invite_endpoint`'s docstring is falsifiable rather than decorative. Then the same
    chain attempted by the project_admin, which stops at the resend.
    """
    from api.services.invite_service import issue_invite

    # ── Half one: the chain, run by a caller who can retrieve a token ─────────
    created = await roles["org_admin_a"].post(
        f"/projects/{SLUG}/stakeholders",
        json={"name": "Victim", "email": "victim@corp.test", "is_reviewer": True},
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]

    resend = await roles["org_admin_a"].post(
        f"/projects/{SLUG}/stakeholders/{sid}/resend-invite"
    )
    assert resend.status_code == 200, resend.text
    async with _anon() as anon:
        taken = await anon.post(
            "/auth/accept",
            json={"token": resend.json()["invite_token"], "password": "attacker-chosen"},
        )
    assert taken.status_code == 200, taken.text

    # A second engagement invites the same real person. This is the consultant acting
    # correctly, on a project the attacker has nothing to do with.
    async with get_connection(OTHER_SLUG) as conn:
        other = await fetch_project(conn, slug=OTHER_SLUG)
        victim_row = await insert_stakeholder(
            conn, project_id=other["id"], name="Victim",
            email="victim@corp.test", is_reviewer=True,
        )
    second = await issue_invite(
        email="victim@corp.test", project_slug=OTHER_SLUG, stakeholder_id=victim_row
    )
    async with _anon() as anon:
        redeemed = await anon.post(
            "/auth/accept", json={"token": second, "password": "the-real-persons-password"}
        )
    assert redeemed.status_code == 200, redeemed.text

    async with _client_for("victim@corp.test", "reviewer") as seized:
        reach = await seized.get(f"/projects/{OTHER_SLUG}/milestones")
    assert reach.status_code == 200, (
        "the chain does not actually reach the second engagement - if this is now a 403 the "
        "membership behaviour has changed and resend-invite's docstring needs rewriting"
    )

    # ── Half two: the same chain, attempted by the project_admin ──────────────
    fresh = await roles["padmin"].post(
        f"/projects/{SLUG}/stakeholders",
        json={"name": "Victim Two", "email": "victim2@corp.test", "is_reviewer": True},
    )
    assert fresh.status_code == 201, fresh.text

    blocked = await roles["padmin"].post(
        f"/projects/{SLUG}/stakeholders/{fresh.json()['id']}/resend-invite"
    )
    assert _refusal(blocked) == (403, PLATFORM_TIER_REQUIRED)
    async with get_system_connection() as sys_conn:
        assert await fetch_user(sys_conn, username="victim2@corp.test") is None, (
            "the project_admin pre-registered an account for somebody else - chain B is open"
        )


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
    """The account boundary's other side, driven as the whole chain rather than as a kwarg.

    Stakeholder administration issues an invite the moment a role beyond participant is set
    on somebody with an address, and redeeming one creates a `users` row. That door was
    consultant-only before this branch, so a client-side project_admin causing a login to
    exist is a new capability worth pinning.

    The first version of this test mocked `issue_invite` away and asserted the `project_slug`
    kwarg it was called with. That stops one call short of the thing that matters: it proves
    the router asked for an invite naming this project, and says nothing about what the
    resulting account can reach - which is the whole question. So nothing is mocked here. The
    invite is really issued, really redeemed at the unauthenticated `/auth/accept`, and the
    account it creates is then driven against both engagements.

    What confines it: `accept_token` hard-codes `role="reviewer"` - load-bearing per its own
    comment, because `check_project_access` only attempts the membership lookup for that
    value - and the membership it writes names this project alone.
    """
    created = await roles["padmin"].post(
        f"/projects/{SLUG}/stakeholders",
        json={"name": "Invitee", "email": "invitee@example.com", "is_reviewer": True},
    )
    assert created.status_code == 201, created.text

    raw = await _live_invite_token("invitee@example.com")
    assert raw is not None, "no invite was issued - the chain below would prove nothing"

    async with _anon() as anon:
        accepted = await anon.post(
            "/auth/accept", json={"token": raw, "password": "chosen-by-the-invitee"}
        )
    assert accepted.status_code == 200, accepted.text

    async with get_system_connection() as sys_conn:
        account = await fetch_user(sys_conn, username="invitee@example.com")
    assert account is not None
    assert account["role"] == "reviewer", (
        "a project_admin caused an account carrying a platform tier"
    )

    # What it reaches: this engagement, and only this engagement.
    async with _client_for("invitee@example.com", "reviewer") as invitee:
        assert (await invitee.get(f"/projects/{SLUG}/milestones")).status_code == 200
        assert _refusal(
            await invitee.get(f"/projects/{OTHER_SLUG}/milestones")
        ) == (403, ACCESS_DENIED)
        # And no authority on it beyond membership: the role a redeemed invite mints is
        # read access, not the reviewer *stakeholder* flag the content gates ask about.
        assert (await invitee.get(f"/projects/{SLUG}/my-permissions")).json() == {
            "can_review": True, "can_approve": False, "can_grant_roles": False,
            # Nor may the account a redeemed invite minted go on to mint another: the
            # resend door is platform tier, and this login is not.
            "can_issue_invite_links": False,
            # Nor may it add material to any knowledge store, at any width. Membership is
            # read access by design; writing the project's own store takes administration
            # of this project or approval on it, and this login has neither.
            "writable_knowledge_tiers": [],
        }


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


# ── PATCH /settings is not uniformly project configuration ────────────────────
#
# The body carries `llm_mode`, `dev_mode` and the per-agent model ids alongside the sector
# and the stakeholder groups. CLAUDE.md states the secure-mode guarantee as absolute - every
# crew agent including PAM routes locally on a sensitive project, a missing local model
# raises LocalModelUnavailable rather than falling back, documents stay off Chroma Cloud -
# and widening this door handed the switch to the client's own administrator.
#
# The stored mode is read from `projects.llm_mode` afterwards in every test here, never from
# the response. A 403 says the request was refused; it does not say nothing was written.


async def _stored_llm_mode(slug: str) -> str:
    async with get_connection(slug) as conn:
        return (await fetch_project(conn, slug=slug))["llm_mode"]


@pytest_asyncio.fixture
async def sensitive_project(roles, client):
    """Turn the test project sensitive, using the platform tier that is allowed to."""
    settings = (await client.get(f"/projects/{SLUG}/settings")).json()
    r = await client.patch(
        f"/projects/{SLUG}/settings", json={**settings, "llm_mode": "sensitive"}
    )
    assert r.status_code == 200, r.text
    assert await _stored_llm_mode(SLUG) == "sensitive", "precondition"
    return settings


@pytest.mark.asyncio
async def test_a_project_admin_cannot_switch_a_sensitive_project_to_hosted(
    roles, sensitive_project
):
    """The finding, stated where it lands. Asserted on the stored column, not the status."""
    r = await roles["padmin"].patch(
        f"/projects/{SLUG}/settings", json={**sensitive_project, "llm_mode": "standard"}
    )

    status, detail = _refusal(r)
    assert status == 403, r.text
    assert "llm_mode" in detail, detail
    assert await _stored_llm_mode(SLUG) == "sensitive", (
        "the project was downgraded to hosted anyway - the refusal is decoration"
    )


@pytest.mark.asyncio
async def test_omitting_llm_mode_does_not_silently_downgrade_a_sensitive_project(
    roles, sensitive_project
):
    """The defaults trap, which is the quieter half of the same hole. `ProjectSettings`
    defaults `llm_mode` to "standard", so a body that simply leaves the key out asks for a
    downgrade without ever naming one. Refused as the change it is."""
    body = {k: v for k, v in sensitive_project.items() if k != "llm_mode"}

    r = await roles["padmin"].patch(f"/projects/{SLUG}/settings", json=body)

    assert _refusal(r)[0] == 403, r.text
    assert await _stored_llm_mode(SLUG) == "sensitive"


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("dev_mode", False),
    ("anthropic_deep_model", "anthropic/claude-opus-4-6-attacker"),
    ("local_deep_url", "http://attacker.test/v1"),
    ("local_fast_model", "exfiltrator:latest"),
])
async def test_a_project_admin_cannot_change_where_this_engagement_sends_its_data(
    roles, field, value
):
    """`llm_mode` is the loudest of these, not the only one. Pointing a tier at another model
    or another base URL reaches the same place quietly, and `dev_mode` is what holds outbound
    project email to a single address."""
    settings = (await roles["padmin"].get(f"/projects/{SLUG}/settings")).json()

    r = await roles["padmin"].patch(
        f"/projects/{SLUG}/settings", json={**settings, field: value}
    )

    status, detail = _refusal(r)
    assert status == 403, r.text
    assert field in detail, detail
    after = (await roles["padmin"].get(f"/projects/{SLUG}/settings")).json()
    assert after[field] == settings[field], "the value was written anyway"


@pytest.mark.asyncio
async def test_the_guard_reads_the_authoritative_mode_not_the_config_json_copy(roles):
    """`projects.llm_mode` is the sole authority for the mode; `config_json` carries a copy
    for the Settings tab to round-trip. Comparing a guard against a copy is how the copy's
    drift becomes a bypass, and the two really can drift - `update_project_settings`
    deliberately keeps `llm_mode` out of config.yaml for exactly this reason, and any write
    that touched one and not the other would separate them.

    Constructed here rather than hoped for: the column says sensitive, the copy still says
    standard. A caller submitting the *stale copy's* value is asking for a downgrade, and a
    guard reading the copy would see no change at all and wave it through - writing
    `llm_mode="standard"` to the column on its way past.
    """
    settings = (await roles["padmin"].get(f"/projects/{SLUG}/settings")).json()
    assert settings["llm_mode"] == "standard", "precondition: the copy says standard"
    async with get_connection(SLUG) as conn:
        await conn.execute(
            "UPDATE projects SET llm_mode='sensitive' WHERE slug=?", (SLUG,)
        )
        await conn.commit()
    assert await _stored_llm_mode(SLUG) == "sensitive"

    r = await roles["padmin"].patch(
        f"/projects/{SLUG}/settings", json={**settings, "llm_mode": "standard"}
    )

    assert _refusal(r)[0] == 403, r.text
    assert await _stored_llm_mode(SLUG) == "sensitive", (
        "a sensitive project was downgraded because the guard trusted a stale copy"
    )


@pytest.mark.asyncio
async def test_a_field_missing_from_a_projects_stored_config_is_still_protected(roles):
    """The fail-open shape, which is the one worth testing because it looks harmless - and
    which turns out to describe **every freshly created project**, not some legacy edge case.

    A `field in current` guard skips any protected field the project's stored `config_json`
    does not carry. `create_project` writes `ProjectCreate.model_dump()`, and `ProjectCreate`
    declares nine fields: of the eight in `_PLATFORM_TIER_SETTINGS`, only `llm_mode` is among
    them. So on a project nobody has done a full settings save on yet - which is every project
    up to its first save - such a guard would have protected the mode and nothing else, and a
    project_admin could have repointed both model tiers and cleared `dev_mode` freely.

    `ProjectSettings` defaults are applied to both sides instead, which is also what the
    caller sees: `GET /settings` returns through the same model, so the value being compared
    against is the value that was served.

    The absence is asserted rather than manufactured, so this test fails loudly if
    `create_project` ever starts writing the full settings model - at which point this is
    still true, but for a weaker reason, and the docstring above needs revisiting.
    """
    import json

    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        config = json.loads(project["config_json"] or "{}")
    assert "dev_mode" not in config, (
        "a fresh project's config_json now carries dev_mode - see this test's docstring"
    )

    settings = (await roles["padmin"].get(f"/projects/{SLUG}/settings")).json()
    assert settings["dev_mode"] is True, "the model default is what the caller sees"

    r = await roles["padmin"].patch(
        f"/projects/{SLUG}/settings", json={**settings, "dev_mode": False}
    )

    status, detail = _refusal(r)
    assert status == 403, r.text
    assert "dev_mode" in detail, detail
    after = (await roles["padmin"].get(f"/projects/{SLUG}/settings")).json()
    assert after["dev_mode"] is True, (
        "dev_mode was cleared because it was absent from this project's stored config"
    )


@pytest.mark.asyncio
async def test_a_project_admin_may_still_configure_everything_else(roles, sensitive_project):
    """The success side, and it carries the whole point of comparing the *transition* rather
    than refusing the field's presence: the Settings tab round-trips the entire body, so every
    real save a project_admin makes carries `llm_mode` at its current value. If this refused,
    the door would be closed to them rather than narrowed."""
    r = await roles["padmin"].patch(
        f"/projects/{SLUG}/settings",
        json={**sensitive_project, "llm_mode": "sensitive", "sector": "utilities"},
    )

    assert r.status_code == 200, r.text
    assert r.json()["sector"] == "utilities"
    assert await _stored_llm_mode(SLUG) == "sensitive", "an allowed save moved the mode"


@pytest.mark.asyncio
async def test_the_platform_tier_may_still_change_the_mode(roles, sensitive_project, client):
    """Without this the two tests above are satisfied by a guard that refuses everybody, and
    `llm_mode` would be unchangeable rather than protected."""
    r = await client.patch(
        f"/projects/{SLUG}/settings", json={**sensitive_project, "llm_mode": "standard"}
    )

    assert r.status_code == 200, r.text
    assert await _stored_llm_mode(SLUG) == "standard"


# ── The role flags are booleans, and anything else is refused ─────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["false", "true", "no", "", None, []])
async def test_a_non_boolean_role_flag_is_refused_rather_than_coerced(roles, bad):
    """`{"is_project_admin": "false"}` is a non-empty string, so a plain `bool()` read it as
    True - and for a caller entitled to grant, *wrote* True. The API would have set the flag
    in response to a body that says, in the only sense a human reads it, not to.

    Driven as the authorised caller deliberately: an unauthorised one is refused by the
    authority check whatever the value is, so it could not tell coercion from refusal.
    """
    r = await roles["padmin"].patch(
        f"/projects/{SLUG}/stakeholders/{roles['target']}", json={"is_project_admin": bad}
    )

    assert r.status_code == 422, r.text
    assert "is_project_admin" in r.text
    assert (await _stakeholder(SLUG, roles["target"]))["is_project_admin"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("value,expected", [(True, True), (1, True), (False, False), (0, False)])
async def test_the_boolean_shapes_json_really_produces_are_honoured(roles, value, expected):
    """The other side of the strictness: JSON has no distinct integer-boolean, and
    `{"is_governor": 0}` has been a revocation since sp37's round 3. Refusing those would be
    a regression dressed up as rigour."""
    r = await roles["padmin"].patch(
        f"/projects/{SLUG}/stakeholders/{roles['target']}", json={"is_governor": value}
    )

    assert r.status_code == 200, r.text
    assert r.json()["is_governor"] is expected
    assert (await _stakeholder(SLUG, roles["target"]))["is_governor"] is expected


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

    intended = resolve_recipients(stakeholders)
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
