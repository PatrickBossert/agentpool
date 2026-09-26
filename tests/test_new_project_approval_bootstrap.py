"""A project created from nothing, and who can open its first HITL gate.

An owner created a new engagement, uploaded documents, ran Alex's crew, got a value chain he
was happy with, and could not approve it. `caller_roles` walks JWT -> `users` ->
`project_memberships` -> `stakeholders`, and a project created a minute ago has no
stakeholders, so the walk reaches nothing for anybody - including the person who created it.
The engagement was configurable, runnable, and had nobody who could accept a single output.

CLAUDE.md comes within one sentence of this. It records that a fresh project "has no
stakeholders, and therefore nobody the walk could ever reach", and that `is_sys_admin`
bootstraps `project_admin` for exactly that reason - then says, correctly, that it "implies
nothing about content. Administration and content are different axes." Both halves are right.
Together they leave the state this module pins.

**Nothing here widens a gate.** `caller_may_contribute` and `caller_may_approve` are
untouched, and that is the decision sp67 took rather than an omission - the argument is in the
report. What this module does is turn the dead end and the way out of it from prose into
checked state, in three parts:

  1. the dead end - a creator with total administration and no content authority, refused on
     the first gate by name;
  2. **why seeding the creator as an approver stakeholder at creation would not have fixed
     it** - the option that reads as the obvious repair, driven and shown not to work, so that
     nobody implements it on the strength of it sounding right;
  3. the route out that does work - stakeholder, invite, accept - so the repair a consultant
     is now told to perform is a property of the suite rather than a paragraph.

Driven over HTTP throughout. The brief for this work asked for exactly that and said why: a
unit test of the predicate would pass whether or not any handler consults it. The caller is
the **built-in env-var administrator**, because that is the login that creates engagements on
this deployment and it is the one the walk can never reach - `POST /auth/login` matches
`ADMIN_USERNAME` before it reads `users`, so it has no row there at all.
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
)

SLUG = "approval-bootstrap-tau"

# The sentence `resolve_hitl_review` refuses with. Asserted verbatim rather than by status,
# because a caller refused by two gates at once is a witness to neither - the membership floor
# says "Access denied to this project" and this says something else entirely. It is also the
# sentence the dialog now puts in front of the reviewer, so a change here that left the copy
# alone would be caught on one side or the other.
CONTENT_REFUSAL = "Only a reviewer or approver may resolve a review"


def _sysadmin_headers() -> dict:
    """The built-in administrator's token: a `role='sysadmin'` claim for a login `users` has
    never heard of. Minted the way `POST /auth/login` mints it for `ADMIN_USERNAME`."""
    s = get_settings()
    return {"Authorization": f"Bearer {create_access_token(s.admin_username, 'sysadmin', s.jwt_secret)}"}


@pytest_asyncio.fixture
async def creator():
    """A client holding the built-in administrator's token."""
    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=_sysadmin_headers()
    ) as c:
        yield c


@pytest_asyncio.fixture
async def anon():
    """No Authorization header at all - `POST /auth/accept` takes none, deliberately."""
    from api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture(autouse=True)
async def _clean_shared_state():
    """Remove every trace of this slug on both sides of every test - **both** databases.

    Two halves, and each is useless without the other. `POST /projects` answers 200 to a
    re-POST of an existing slug rather than creating anything, so a project file left behind by
    an earlier test carries its stakeholders into the next one: the empty-roster premise of the
    last test in this module failed exactly that way, reading 2 where it required 0, and it
    would have self-healed on a second run only by accident of ordering.

    The system half is the one no `.db` unlink reaches. `project_registry` lives in `system.db`
    and registration is `INSERT OR IGNORE`, so a stale row silently owns the slug and the
    project created here inherits an owner it never chose; the invite this module redeems also
    leaves an `auth_tokens` row and a `project_memberships` row there. CLAUDE.md records both
    halves of this trap; the pair below is what following it actually looks like.

    `@pytest_asyncio.fixture`, not `@pytest.fixture`: under `asyncio_mode = strict` an async
    fixture declared the plain way is handed over as an un-awaited async generator, so the body
    never runs and nothing anywhere complains. Two files on this project carried exactly that
    and had never deleted a row between them.
    """
    import shutil
    from pathlib import Path

    from api.database import get_db_path

    async def scrub():
        async with get_system_connection() as conn:
            await conn.execute("DELETE FROM project_registry WHERE slug=?", (SLUG,))
            await conn.execute(
                "DELETE FROM project_memberships WHERE project_slug=?", (SLUG,)
            )
            await conn.execute("DELETE FROM auth_tokens WHERE project_slug=?", (SLUG,))
            await conn.execute("DELETE FROM scheduled_jobs WHERE slug=?", (SLUG,))
            # The login the invite mints, so a re-run redeems a fresh invite rather than
            # meeting a `users.username` UNIQUE collision.
            await conn.execute(
                "DELETE FROM users WHERE username=?", ("dana.whitfield@client.test",)
            )
            await conn.commit()
        db = get_db_path(SLUG)
        for suffix in ("", "-wal", "-shm"):
            Path(str(db) + suffix).unlink(missing_ok=True)
        shutil.rmtree(Path(get_settings().projects_dir) / SLUG, ignore_errors=True)

    await scrub()
    yield
    await scrub()


async def _create_project(client: AsyncClient) -> None:
    """The engagement, through the door a consultant uses. Nothing is seeded by hand."""
    r = await client.post("/projects", json={"client_slug": SLUG, "sector": "energy"})
    assert r.status_code in (200, 201), r.text


async def _open_a_gate(prompt: str = "Please review the value chain.\n\nReply approved…") -> int:
    """The first HITL gate, written the way `HumanInputTool` writes it.

    A `human_reviews` row with `decision='pending'` and no `output_id` - which is the shape
    the tool produces (`insert_hitl_review` in `agents/tools/_db.py`) and the shape the
    approval pane reads. Written directly rather than by running a crew: the gate is what is
    under test, not the crew that raises it, and a real run costs money.
    """
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        cur = await conn.execute(
            "INSERT INTO crew_runs (project_id, crew_name, status) VALUES (?,?,?)",
            (project["id"], "discovery_mapping", "running"),
        )
        run_id = cur.lastrowid
        cur = await conn.execute(
            "INSERT INTO human_reviews (crew_run_id, decision, prompt) VALUES (?,?,?)",
            (run_id, "pending", prompt),
        )
        review_id = cur.lastrowid
        await conn.commit()
    return review_id


# ── 1. The dead end ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_creator_of_a_fresh_project_administers_everything_and_may_approve_nothing(
    creator,
):
    """The two axes, measured on one caller at one moment.

    Asserted as a pair rather than as two facts, because each alone reads as the system
    working: "administers everything" is correct and "may approve nothing" is correct, and the
    engagement is unusable only because both are true of the same person at once.
    """
    await _create_project(creator)

    r = await creator.get(f"/projects/{SLUG}/my-permissions")
    assert r.status_code == 200, r.text
    perms = r.json()

    assert perms["can_administer_project"] is True, (
        "the creator cannot administer the engagement they just created - this is a different "
        "and larger defect than the one this module is about"
    )
    assert perms["can_review"] is False
    assert perms["can_approve"] is False


@pytest.mark.asyncio
async def test_the_walk_reaches_nothing_because_the_built_in_administrator_has_no_users_row(
    creator,
):
    """Where the walk actually stops, which decides which repairs are even possible.

    It is not that the stakeholder row is missing - it is that step one fails. `POST
    /auth/login` matches `ADMIN_USERNAME` from the environment before it looks at `users` and
    mints a `sysadmin` token for a login the system database has never heard of, so
    `caller_roles` returns at `if not user`. Every repair below is measured against this fact.
    """
    from api.services.authority_service import caller_roles

    await _create_project(creator)
    s = get_settings()

    async with get_system_connection() as conn:
        assert await fetch_user(conn, username=s.admin_username) is None, (
            "the built-in administrator now has a `users` row, which changes the whole "
            "analysis in this module - re-derive it before adjusting anything here"
        )

    roles = await caller_roles(SLUG, {"sub": s.admin_username, "role": "sysadmin"})
    assert roles == set()


@pytest.mark.asyncio
async def test_the_first_hitl_gate_is_refused_to_its_own_creator_by_the_content_gate(creator):
    """The failure the owner met, end to end, attributed to the gate that caused it.

    On the exact sentence, not on 403 alone: the membership floor would also answer 403 and
    would mean something entirely different, and `resolve_hitl_review` asks the content gate
    *after* the floor.
    """
    await _create_project(creator)
    review_id = await _open_a_gate()

    r = await creator.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "approved", "notes": ""},
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == CONTENT_REFUSAL


# ── 2. The repair that looks obvious and does not work ────────────────────────


@pytest.mark.asyncio
async def test_seeding_an_approver_stakeholder_for_the_creator_does_not_open_the_gate(creator):
    """Why "seed the creator as an approver stakeholder at project creation" was refused.

    It is the repair that keeps both axes intact and sounds right, and on this deployment it
    accomplishes nothing at all. The stakeholder row is created, through the real door, with
    both content flags set - and the creator's authority does not move, because a stakeholder
    row is the **last** step of the walk and the built-in administrator fails the first. There
    is no `users` row for a `project_memberships` row to point from.

    Driven rather than argued, because a seed written on the strength of the argument alone
    would ship a `create_project` that writes to a second database on every call and closes
    nothing. The only way to make it work would be to mint a `users` row for the env-var
    administrator - an account with no settable password, inert for login because `POST
    /auth/login` returns before reading the table, and live for authority. That is a worse
    thing than the defect.
    """
    await _create_project(creator)

    seeded = await creator.post(
        f"/projects/{SLUG}/stakeholders",
        json={
            "name": "The Creator",
            "email": "creator@example.test",
            "is_reviewer": True,
            "is_approver": True,
        },
    )
    assert seeded.status_code == 201, seeded.text
    assert seeded.json()["is_approver"] is True, (
        "the flags did not land, so this test is measuring a failed write rather than the "
        "walk - the premise is gone, not confirmed"
    )

    r = await creator.get(f"/projects/{SLUG}/my-permissions")
    assert r.json()["can_review"] is False
    assert r.json()["can_approve"] is False

    review_id = await _open_a_gate()
    refused = await creator.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "approved", "notes": ""},
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == CONTENT_REFUSAL


# ── 3. The route out, which is what the surface now names ─────────────────────


@pytest.mark.asyncio
async def test_the_documented_repair_opens_the_gate_through_the_products_own_doors(
    creator, anon,
):
    """Stakeholder, invite, accept - and the gate opens. The whole point of option 3.

    This is the sequence the approval pane now tells a consultant to perform, and it is
    asserted here so that the instruction cannot rot into advice that no longer works. Every
    step is a door in the shipped product: `POST /{slug}/stakeholders` with a content flag,
    `POST .../resend-invite` for the token, and the unauthenticated `POST /auth/accept` to
    redeem it, which is what writes the `project_memberships` row the walk starts from.

    The person who ends up holding the authority is a **named individual with an address and a
    login**, not the shared env-var credential - which is the substantive reason this route was
    preferred to letting `is_sys_admin` satisfy the content gates. A client engagement's
    canonical value chain should not be accepted by "admin".

    Asserted on the gate actually resolving, not on the permission flag flipping: a flag is one
    layer away from the property, and CLAUDE.md's most repeated finding on this codebase is a
    test that lands beside the thing it is about rather than on it.
    """
    await _create_project(creator)
    review_id = await _open_a_gate()

    created = await creator.post(
        f"/projects/{SLUG}/stakeholders",
        json={
            "name": "Dana Whitfield",
            "email": "dana.whitfield@client.test",
            "is_reviewer": True,
            "is_approver": True,
        },
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]

    resend = await creator.post(f"/projects/{SLUG}/stakeholders/{sid}/resend-invite")
    assert resend.status_code == 200, resend.text

    redeemed = await anon.post(
        "/auth/accept",
        json={"token": resend.json()["invite_token"], "password": "a-real-password-1"},
    )
    assert redeemed.status_code == 200, redeemed.text

    s = get_settings()
    approver_token = create_access_token(
        "dana.whitfield@client.test", "reviewer", s.jwt_secret
    )
    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {approver_token}"},
    ) as approver:
        perms = await approver.get(f"/projects/{SLUG}/my-permissions")
        assert perms.status_code == 200, perms.text
        assert perms.json()["can_review"] is True
        assert perms.json()["can_approve"] is True

        resolved = await approver.patch(
            f"/projects/{SLUG}/reviews/{review_id}",
            json={"decision": "approved", "notes": ""},
        )

    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["decision"] == "approved"

    # The gate is actually released, which is what the crew polls for. Asserted on the row
    # because that is what `HumanInputTool` reads; a 200 from the door says the request was
    # accepted and not that the crew can proceed.
    async with get_connection(SLUG) as conn:
        cur = await conn.execute(
            "SELECT decision FROM human_reviews WHERE id=?", (review_id,)
        )
        assert (await cur.fetchone())["decision"] == "approved"


@pytest.mark.asyncio
async def test_the_content_gates_were_not_widened_for_the_built_in_administrator(creator):
    """The decision, stated as an assertion so it cannot be softened without a failing test.

    sp67 deliberately did **not** let `is_sys_admin` satisfy the content gates on a project
    with no stakeholders. Two reasons, and the second is the one that makes it a rule rather
    than a preference: "no stakeholders" is a state a populated project can return to, so the
    authority of a caller who never changed would depend on whether somebody else's row had
    been deleted; and the caller it would empower is a shared environment-variable credential,
    so every approval on every engagement would be attributed to the operator.

    This is the test that fails if a later change takes the cheap route. It is deliberately
    written against the gate on a project whose stakeholder table is **empty**, which is the
    precise condition such a change would special-case.
    """
    from api.services.authority_service import caller_may_approve, caller_may_contribute

    await _create_project(creator)
    s = get_settings()
    payload = {"sub": s.admin_username, "role": "sysadmin"}

    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        cur = await conn.execute(
            "SELECT COUNT(*) AS n FROM stakeholders WHERE project_id=?", (project["id"],)
        )
        assert (await cur.fetchone())["n"] == 0, "the premise of this test is an empty roster"

    assert await caller_may_contribute(SLUG, payload) is False
    assert await caller_may_approve(SLUG, payload) is False
