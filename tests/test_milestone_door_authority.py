"""The milestone, calendar, branding, PAM-report, and interview-session doors, over HTTP.

`milestones.py` and `nonworking.py` used to import `require_any_auth` under the alias
`get_current_user`, so every handler read `Depends(get_current_user)` and looked exactly like
a properly gated one. Neither called `check_project_access`, and neither applied a second
gate - which made every door in them a project-scoped read or write that *any* valid token
could make against *any* slug. `POST /{slug}/branding/image` was the same defect under
`get_token_payload`.

The cross-project case is the whole point, and it is what an "anonymous is refused" test would
have missed entirely: before this branch a legitimate, fully-privileged administrator of
engagement A could rewrite engagement B's milestones, because nothing on the door ever asked
which engagement the caller belonged to. `admin_a` below is exactly that caller - a real
org_admin login whose organisation owns project A and not project B - and every refusal it
receives on B is `check_project_access` and nothing else, since it clears the administration
dependency on its login role alone.

The callers are chosen so that each refusal is attributable to one gate:

  outsider  - a real login with no membership anywhere. Refused by the membership floor.
  member    - a real login, membership on A, a stakeholder row flagged is_participant only.
              Clears the floor; refused on writes by the administration axis.
  approver  - the same wiring with is_reviewer and is_approver, for the content gate.
  admin_a   - org_admin of the organisation owning A. Clears the administration axis
              everywhere, and the floor only on A.

Refusals are asserted on their `detail` as well as their status, because a caller refused by
two gates at once tells you nothing about either. "Access denied to this project" is
`check_project_access`; "Org admin or above required" is `require_org_admin_or_above`; "Only
an approver may re-baseline a milestone" is the content gate.

Two further reads were found by sweeping every handler mounted under a `/projects/{slug}`
prefix - by behaviour, not by name, because the alias hid two files from a `require_any_auth`
grep and `pam_report.py` then hid from the alias sweep by not aliasing. Both are covered at
the foot of this module:

  GET /projects/{slug}/pam-report        - run status, milestone variance, output summaries
  GET /api/interviews/sessions/{slug}    - every stakeholder's `session_token`

The second is the worse of the two by some distance. A session token is the only credential
the rest of the interview API checks, so an unscoped read of that list is not merely a
disclosure - it is a way in through the public half of the interview router as somebody
else's interviewee.
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.auth import create_access_token
from api.config import get_settings
from api.database import (
    fetch_project,
    fetch_user,
    get_connection,
    get_system_connection,
    insert_organisation,
    insert_project_registry,
    insert_stakeholder,
    insert_user,
    link_membership,
)

SLUG_A = "gate-doors-alpha"
SLUG_B = "gate-doors-beta"

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32

ACCESS_DENIED = "Access denied to this project"
ADMIN_REQUIRED = "Org admin or above required"
APPROVER_REQUIRED = "Only an approver may re-baseline a milestone"


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


async def _seed_member(slug: str, *, username: str, **flags) -> None:
    """A login wired the whole way - users row, membership, stakeholder on this project."""
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


@pytest_asyncio.fixture
async def doors(tmp_path, monkeypatch, client):
    """Two projects owned by two different organisations, one milestone each, four callers.

    DATABASE_DIR and PROJECTS_DIR are redirected at this test's own tmp_path: the system
    database holding `users`, `project_memberships` and `project_registry` otherwise lives
    at the shared, persistent /tmp/agentpool_test, and these fixtures insert users by a
    fixed username - which passes once and fails on every run afterwards.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()

    milestone_ids: dict[str, int] = {}
    for slug in (SLUG_A, SLUG_B):
        r = await client.post("/projects", json=_project_body(slug))
        assert r.status_code in (200, 201), r.text
        r = await client.post(
            f"/projects/{slug}/milestones",
            json={"title": "Kickoff", "due_date": "2026-08-10"},
        )
        assert r.status_code in (200, 201), r.text
        milestone_ids[slug] = r.json()["id"]
        # Activation is itself approver-gated and none of these tests are about that gate,
        # so the baseline a re-baseline needs is set directly. Without one, rebaseline_
        # milestone answers 404 and the approver's success below could not be asserted.
        async with get_connection(slug) as conn:
            await conn.execute(
                "UPDATE project_milestones SET baseline_date='2026-08-10' WHERE id=?",
                (milestone_ids[slug],),
            )
            await conn.commit()

    async with get_system_connection() as sys_conn:
        org_a = await insert_organisation(sys_conn, slug="org-alpha", name="Alpha")
        org_b = await insert_organisation(sys_conn, slug="org-beta", name="Beta")
        await insert_project_registry(
            sys_conn, slug=SLUG_A, org_id=org_a, display_name=SLUG_A
        )
        await insert_project_registry(
            sys_conn, slug=SLUG_B, org_id=org_b, display_name=SLUG_B
        )
        await insert_user(
            sys_conn, username="door-outsider", email="outsider@example.com",
            role="reviewer", hashed_pw="x",
        )
        await sys_conn.commit()

    await _seed_member(SLUG_A, username="door-member", is_participant=True)
    await _seed_member(SLUG_A, username="door-approver", is_reviewer=True, is_approver=True)

    # A real orchestration run and a real interview session on project A, so
    # GET /api/interviews/sessions/{slug} has an actual session_token to hand out. Without
    # one the endpoint answers an empty list to everybody, and "a member may read it" could
    # not tell a working read from a broken one. Written with raw SQL rather than
    # api.database.insert_interview_session, which CLAUDE.md records as having no
    # production caller and being driven by tests alone - leaning on it here would add
    # another test to the pile keeping a dead helper alive.
    async with get_connection(SLUG_A) as conn:
        project = await fetch_project(conn, slug=SLUG_A)
        cur = await conn.execute(
            "INSERT INTO orchestration_runs (project_id, status) VALUES (?, 'running')",
            (project["id"],),
        )
        run_id = cur.lastrowid
        cur = await conn.execute(
            "SELECT id FROM stakeholders WHERE project_id=? ORDER BY id LIMIT 1",
            (project["id"],),
        )
        stakeholder_id = (await cur.fetchone())["id"]
        await conn.execute(
            "INSERT INTO interview_sessions"
            " (project_id, orchestration_run_id, stakeholder_id, node_label, session_token)"
            " VALUES (?,?,?,?,?)",
            (project["id"], run_id, stakeholder_id, "1.2 Portfolio", "tok-alpha-secret"),
        )
        await conn.commit()

    outsider = _client_for("door-outsider", "reviewer")
    member = _client_for("door-member", "reviewer")
    approver = _client_for("door-approver", "reviewer")
    admin_a = _client_for("door-admin-a", "org_admin", org_id=org_a)

    async with outsider, member, approver, admin_a:
        yield {
            "outsider": outsider,
            "member": member,
            "approver": approver,
            "admin_a": admin_a,
            "milestone_a": milestone_ids[SLUG_A],
            "milestone_b": milestone_ids[SLUG_B],
            "org_b": org_b,
        }

    get_settings.cache_clear()


def _refusal(resp) -> tuple[int, str]:
    """Status and refusal reason. A door that let the caller through answers its own
    payload, which has no `detail` - reported as the body itself rather than raising, so a
    gate that stops refusing fails these tests on the assertion instead of on a TypeError."""
    body = resp.json()
    if isinstance(body, dict) and "detail" in body:
        return resp.status_code, body["detail"]
    return resp.status_code, f"<allowed: {body!r}>"


# ── Controls ──────────────────────────────────────────────────────────────────
#
# Every refusal below is only worth reading if these hold. Without them a gate that refused
# unconditionally, or a caller mis-wired so it was never inside the project at all, would
# satisfy the whole module.

@pytest.mark.asyncio
async def test_the_member_really_is_inside_project_a(doors):
    r = await doors["member"].get(f"/projects/{SLUG_A}/milestones")
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_the_administrator_really_can_write_to_project_a(doors):
    r = await doors["admin_a"].post(
        f"/projects/{SLUG_A}/milestones", json={"title": "Phase 2", "due_date": "2026-09-01"}
    )
    assert r.status_code in (200, 201), r.text


# ── The membership floor, on reads ────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    f"/projects/{SLUG_A}/milestones",
    f"/projects/{SLUG_A}/nonworking",
])
async def test_a_caller_with_no_membership_cannot_read(doors, path):
    assert _refusal(await doors["outsider"].get(path)) == (403, ACCESS_DENIED)


@pytest.mark.asyncio
async def test_a_caller_with_no_membership_cannot_read_baselines(doors):
    path = f"/projects/{SLUG_A}/milestones/{doors['milestone_a']}/baselines"
    assert _refusal(await doors["outsider"].get(path)) == (403, ACCESS_DENIED)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    f"/projects/{SLUG_A}/milestones",
    f"/projects/{SLUG_A}/nonworking",
])
async def test_membership_alone_is_read_access(doors, path):
    """The other half of the rule, and the half a refusal-only test cannot express: a
    participant holds no administration role and no content role whatever, and still reads
    the engagement they belong to."""
    assert (await doors["member"].get(path)).status_code == 200


# ── The administration axis, on writes ────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_member_without_administration_cannot_write_milestones(doors):
    m = doors["milestone_a"]
    calls = [
        doors["member"].post(f"/projects/{SLUG_A}/milestones/seed"),
        doors["member"].post(f"/projects/{SLUG_A}/milestones", json={"title": "Sneak"}),
        doors["member"].patch(f"/projects/{SLUG_A}/milestones/{m}", json={"title": "Moved"}),
        doors["member"].delete(f"/projects/{SLUG_A}/milestones/{m}"),
    ]
    for call in calls:
        assert _refusal(await call) == (403, ADMIN_REQUIRED)


@pytest.mark.asyncio
async def test_a_member_without_administration_cannot_write_nonworking_ranges(doors):
    body = {"label": "Shutdown", "start_date": "2026-12-24", "end_date": "2027-01-02"}
    calls = [
        doors["member"].post(f"/projects/{SLUG_A}/nonworking", json=body),
        doors["member"].patch(f"/projects/{SLUG_A}/nonworking/1", json=body),
        doors["member"].delete(f"/projects/{SLUG_A}/nonworking/1"),
    ]
    for call in calls:
        assert _refusal(await call) == (403, ADMIN_REQUIRED)


@pytest.mark.asyncio
async def test_a_member_without_administration_cannot_upload_branding(doors):
    r = await doors["member"].post(
        f"/projects/{SLUG_A}/branding/image",
        files={"file": ("header.png", PNG, "image/png")},
    )
    assert _refusal(r) == (403, ADMIN_REQUIRED)


@pytest.mark.asyncio
async def test_an_administrator_of_this_project_may_write_all_of_it(doors):
    """The success side. Without it the module would be satisfied by gates that refuse
    everyone, and the doors would be closed rather than gated."""
    admin = doors["admin_a"]
    assert (await admin.post(f"/projects/{SLUG_A}/milestones/seed")).status_code == 200

    created = await admin.post(
        f"/projects/{SLUG_A}/milestones", json={"title": "Handover", "due_date": "2026-10-01"}
    )
    assert created.status_code in (200, 201), created.text
    new_id = created.json()["id"]
    assert (await admin.patch(
        f"/projects/{SLUG_A}/milestones/{new_id}", json={"title": "Handover (revised)"}
    )).status_code == 200
    assert (await admin.delete(f"/projects/{SLUG_A}/milestones/{new_id}")).status_code == 204

    body = {"label": "Shutdown", "start_date": "2026-12-24", "end_date": "2027-01-02"}
    made = await admin.post(f"/projects/{SLUG_A}/nonworking", json=body)
    assert made.status_code == 201, made.text
    range_id = made.json()["id"]
    assert (await admin.patch(
        f"/projects/{SLUG_A}/nonworking/{range_id}", json={**body, "label": "Works shutdown"}
    )).status_code == 200
    assert (await admin.delete(f"/projects/{SLUG_A}/nonworking/{range_id}")).status_code == 204

    uploaded = await admin.post(
        f"/projects/{SLUG_A}/branding/image",
        files={"file": ("header.png", PNG, "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text


# ── The cross-project hole itself ─────────────────────────────────────────────
#
# admin_a clears `require_org_admin_or_above` on every one of these calls - the dependency
# reads the JWT role and knows nothing of slugs. So `check_project_access` is the only thing
# standing between this caller and another organisation's engagement, and removing that one
# line turns every assertion here into a success.

@pytest.mark.asyncio
async def test_an_administrator_of_another_engagement_cannot_read_this_one(doors):
    admin = doors["admin_a"]
    m = doors["milestone_b"]
    assert _refusal(await admin.get(f"/projects/{SLUG_B}/milestones")) == (403, ACCESS_DENIED)
    assert _refusal(await admin.get(f"/projects/{SLUG_B}/nonworking")) == (403, ACCESS_DENIED)
    assert _refusal(
        await admin.get(f"/projects/{SLUG_B}/milestones/{m}/baselines")
    ) == (403, ACCESS_DENIED)


@pytest.mark.asyncio
async def test_an_administrator_of_another_engagement_cannot_rewrite_these_milestones(doors):
    admin = doors["admin_a"]
    m = doors["milestone_b"]
    calls = [
        admin.post(f"/projects/{SLUG_B}/milestones/seed"),
        admin.post(f"/projects/{SLUG_B}/milestones", json={"title": "Not yours"}),
        admin.patch(f"/projects/{SLUG_B}/milestones/{m}", json={"title": "Rewritten"}),
        admin.delete(f"/projects/{SLUG_B}/milestones/{m}"),
        admin.post(
            f"/projects/{SLUG_B}/milestones/{m}/rebaseline",
            json={"baseline_date": "2026-11-01", "reason": "not their call"},
        ),
    ]
    for call in calls:
        assert _refusal(await call) == (403, ACCESS_DENIED)


@pytest.mark.asyncio
async def test_an_administrator_of_another_engagement_cannot_change_its_calendar(doors):
    admin = doors["admin_a"]
    body = {"label": "Shutdown", "start_date": "2026-12-24", "end_date": "2027-01-02"}
    calls = [
        admin.post(f"/projects/{SLUG_B}/nonworking", json=body),
        admin.patch(f"/projects/{SLUG_B}/nonworking/1", json=body),
        admin.delete(f"/projects/{SLUG_B}/nonworking/1"),
    ]
    for call in calls:
        assert _refusal(await call) == (403, ACCESS_DENIED)


@pytest.mark.asyncio
async def test_an_administrator_of_another_engagement_cannot_rebrand_it(doors):
    r = await doors["admin_a"].post(
        f"/projects/{SLUG_B}/branding/image",
        files={"file": ("header.png", PNG, "image/png")},
    )
    assert _refusal(r) == (403, ACCESS_DENIED)


@pytest.mark.asyncio
async def test_the_milestones_of_the_other_engagement_are_untouched(doors):
    """A 403 says the request was refused; it does not say nothing was written.

    The calls are made here rather than relied on from the test above: the fixture is
    function-scoped, so a test that only read project B's row back would be asserting
    against a database nothing had ever been asked to change.
    """
    admin = doors["admin_a"]
    m = doors["milestone_b"]
    await admin.patch(f"/projects/{SLUG_B}/milestones/{m}", json={"title": "Rewritten"})
    await admin.post(
        f"/projects/{SLUG_B}/milestones/{m}/rebaseline",
        json={"baseline_date": "2026-11-01", "reason": "not their call"},
    )
    await admin.delete(f"/projects/{SLUG_B}/milestones/{m}")

    async with get_connection(SLUG_B) as conn:
        async with conn.execute(
            "SELECT title, baseline_date FROM project_milestones WHERE id=?",
            (doors["milestone_b"],),
        ) as cur:
            row = await cur.fetchone()
    assert row is not None, "project B's milestone was deleted by a caller from project A"
    assert row["title"] == "Kickoff"
    assert row["baseline_date"] == "2026-08-10"


# ── Re-baselining keeps the content gate, and gains the floor ─────────────────

@pytest.mark.asyncio
async def test_rebaselining_refuses_a_non_member_on_the_membership_floor(doors):
    """Both gates would refuse this caller, so the status code alone proves nothing about
    which. The detail does: `check_project_access` runs first, and with that line removed
    this answers the content gate's message instead."""
    r = await doors["outsider"].post(
        f"/projects/{SLUG_A}/milestones/{doors['milestone_a']}/rebaseline",
        json={"baseline_date": "2026-08-24", "reason": "CR-014"},
    )
    assert _refusal(r) == (403, ACCESS_DENIED)


@pytest.mark.asyncio
async def test_rebaselining_still_refuses_a_member_without_the_content_role(doors):
    """The floor must not have quietly replaced the gate it was added beside. This caller
    passes `check_project_access` and is refused by `caller_may_commit`."""
    r = await doors["member"].post(
        f"/projects/{SLUG_A}/milestones/{doors['milestone_a']}/rebaseline",
        json={"baseline_date": "2026-08-24", "reason": "CR-014"},
    )
    assert _refusal(r) == (403, APPROVER_REQUIRED)


@pytest.mark.asyncio
async def test_an_approver_on_this_project_may_still_rebaseline(doors):
    r = await doors["approver"].post(
        f"/projects/{SLUG_A}/milestones/{doors['milestone_a']}/rebaseline",
        json={"baseline_date": "2026-08-24", "reason": "CR-014"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["baseline_date"] == "2026-08-24"


@pytest.mark.asyncio
async def test_rebaselining_is_not_on_the_administration_axis(doors):
    """The one door in this router that did not move. An org_admin who belongs to the
    engagement still has no content authority on it - if re-baselining had been swept onto
    the administration axis with its neighbours, this would succeed."""
    r = await doors["admin_a"].post(
        f"/projects/{SLUG_A}/milestones/{doors['milestone_a']}/rebaseline",
        json={"baseline_date": "2026-09-24", "reason": "CR-020"},
    )
    assert _refusal(r) == (403, APPROVER_REQUIRED)


# ── The two reads the behavioural sweep found ─────────────────────────────────
#
# Neither router aliased anything, which is why neither turned up in the sweep that found
# `milestones.py` and `nonworking.py`. Both are pure `check_project_access` omissions of the
# same shape: a `/projects/{slug}`-scoped read behind `require_any_auth`, which asks whether
# the caller has a login and never which engagement the login is on.
#
# `admin_a` carries the weight here for the same reason as above - it is a real, legitimate,
# fully-privileged administrator, refused only because the engagement is not its own.

PAM_REPORT = "/projects/{slug}/pam-report"
SESSIONS = "/api/interviews/sessions/{slug}"


@pytest.mark.asyncio
@pytest.mark.parametrize("template", [PAM_REPORT, SESSIONS])
async def test_a_caller_with_no_membership_cannot_read_it(doors, template):
    path = template.format(slug=SLUG_A)
    assert _refusal(await doors["outsider"].get(path)) == (403, ACCESS_DENIED)


@pytest.mark.asyncio
@pytest.mark.parametrize("template", [PAM_REPORT, SESSIONS])
async def test_an_administrator_of_another_engagement_cannot_read_it(doors, template):
    """The cross-project case. `admin_a` clears every login-role check these doors have;
    remove `check_project_access` and both of these become successes."""
    path = template.format(slug=SLUG_B)
    assert _refusal(await doors["admin_a"].get(path)) == (403, ACCESS_DENIED)


@pytest.mark.asyncio
@pytest.mark.parametrize("template", [PAM_REPORT, SESSIONS])
async def test_a_member_may_still_read_it(doors, template):
    """The success side, and not decoration: without it the module is satisfied by a gate
    that refuses everyone, which closes the door rather than gating it. `member` holds a
    participant stakeholder and no other role at all - membership is read access."""
    path = template.format(slug=SLUG_A)
    resp = await doors["member"].get(path)
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_reading_interview_sessions_really_does_hand_out_a_session_token(doors):
    """Why the sessions door is the sharper of the two, checked rather than merely claimed.

    A session token is the only credential the public half of `api/routers/interviews.py`
    checks, so an unscoped read here is not a disclosure of project metadata - it is a way
    in as somebody else's interviewee. Asserting the literal token the fixture seeded is
    what makes the severity argument in this module's docstring falsifiable: if the
    endpoint ever stops returning tokens, this fails and the argument gets rewritten rather
    than quietly rotting into a claim nothing checks.
    """
    body = (await doors["member"].get(SESSIONS.format(slug=SLUG_A))).json()
    tokens = [s["session_token"] for s in body["sessions"]]
    assert tokens == ["tok-alpha-secret"]


@pytest.mark.asyncio
async def test_the_other_engagements_session_tokens_do_not_leak(doors):
    """The refusal, spelled out against the thing being protected. An administrator of the
    other engagement is refused project A's session list, tokens and all."""
    async with _client_for("door-admin-b", "org_admin", org_id=doors["org_b"]) as admin_b:
        resp = await admin_b.get(SESSIONS.format(slug=SLUG_A))
    assert _refusal(resp) == (403, ACCESS_DENIED)
    assert "tok-alpha-secret" not in resp.text


@pytest.mark.asyncio
async def test_probing_an_unknown_slug_creates_no_database(doors, tmp_path):
    """`get_connection(slug)` creates a project database on first touch - mkdir, connect,
    init_db, the full migration block. The sessions handler called it before any access
    check, so a caller walking slugs materialised a file per guess. The gate now runs
    first, and the refusal must arrive without the side effect."""
    from api.database import get_db_path

    unknown = "never-created-engagement"
    assert not get_db_path(unknown).exists(), "fixture setup must not create it either"

    assert _refusal(
        await doors["member"].get(SESSIONS.format(slug=unknown))
    ) == (403, ACCESS_DENIED)
    assert not get_db_path(unknown).exists(), (
        "a refused read must not materialise a project database"
    )
