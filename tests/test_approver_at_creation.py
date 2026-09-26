"""Naming an engagement's first approver at creation, and what that buys.

An owner created an engagement, uploaded documents, ran Alex's crew, liked the value chain,
and could not approve it. `caller_roles` walks JWT -> `users` -> `project_memberships` ->
`stakeholders`; a project created a minute ago had no stakeholders, so the walk reached
nothing for anybody - including the person who created it - and the first `HumanInputTool`
gate sat unopenable for its full twenty-four-hour timeout.
`tests/test_new_project_approval_bootstrap.py` pins that dead end and the two repairs that
do and do not work. This module is about the field that makes it unreachable: `POST /projects`
now requires an approver's name and address, and writes the rows that give them content
authority on the engagement.

**The headline test is `test_the_person_named_at_creation_can_open_the_first_hitl_gate`, and
everything else here supports it.** The brief for this work said why a unit test would not do,
and it is worth restating because it decides the shape of the whole file: the defect was never
in a predicate. `caller_roles` was correct, `caller_may_approve` was correct, and the gate was
correct. What was missing was that **three rows in two databases** - a stakeholder in
`data/<slug>.db`, a `users` row and a `project_memberships` row in `data/system.db` - never came
to exist together. A test of any one layer passes against that.

Four properties here are asserted in **both** directions, because each has a mutation that a
one-sided test cannot see:

  - creation with no approver is refused, *and* a valid one succeeds;
  - a blank or malformed address is refused, *and* a well-formed one is accepted;
  - a failed **stakeholder** write fails the creation, *and* a failed **invite** does not;
  - a re-POST creates no second approver, *and* the first POST did create one.

The last pair is the one CLAUDE.md's "a default and a write are indistinguishable until
something chooses the other value" applies to most directly. "No second stakeholder was
created" is satisfied perfectly by a creation that never created a first.
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.auth import create_access_token
from api.config import get_settings
from api.database import (
    fetch_project,
    fetch_stakeholders,
    get_connection,
    get_system_connection,
)

SLUG = "approver-at-creation-rho"

APPROVER_NAME = "Rosalind Achebe"
APPROVER_EMAIL = "rosalind.achebe@client.test"

# The sentence `resolve_hitl_review` refuses with, asserted verbatim rather than by status.
# A caller refused by the membership floor also answers 403 and means something entirely
# different ("Access denied to this project"), so a status-only assertion would be satisfied
# by the wrong refusal - and this module's whole claim is that the *content* gate now opens.
CONTENT_REFUSAL = "Only a reviewer or approver may resolve a review"


def _body(**overrides) -> dict:
    return {
        "client_slug": SLUG,
        "sector": "energy",
        "approver_name": APPROVER_NAME,
        "approver_email": APPROVER_EMAIL,
        **overrides,
    }


def _sysadmin_headers() -> dict:
    """The built-in administrator, minted the way `POST /auth/login` mints it for
    `ADMIN_USERNAME` - a `role='sysadmin'` claim for a login `users` has never heard of.

    This is the caller that creates engagements on this deployment, and it is deliberately
    the one used throughout: it is the caller for whom seeding a stakeholder accomplishes
    nothing, because `caller_roles` returns at step one for it.
    """
    s = get_settings()
    return {
        "Authorization": f"Bearer {create_access_token(s.admin_username, 'sysadmin', s.jwt_secret)}"
    }


@pytest_asyncio.fixture
async def creator():
    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=_sysadmin_headers()
    ) as c:
        yield c


@pytest_asyncio.fixture
async def anon():
    """No Authorization header. `POST /auth/accept` takes none, deliberately - the token is
    the credential, which is why the doors that hand one out are platform tier."""
    from api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture(autouse=True)
async def _clean_shared_state():
    """Scrub this slug from **both** databases, before and after every test.

    `@pytest_asyncio.fixture` rather than `@pytest.fixture`: under `asyncio_mode = strict` an
    async fixture declared the plain way is handed to the test as an un-awaited async
    generator, so the body never runs and nothing complains. Two files on this project carried
    exactly that and had between them never removed a row.

    The project file is not enough, and this module needs all four system tables. `POST
    /projects` answers **200** to a re-POST rather than creating anything, so a leftover
    project file carries its stakeholders into the next test and the idempotency tests below
    would measure the previous test's rows. `project_registry` is `INSERT OR IGNORE`, so a
    stale row silently owns the slug. And the invite this module redeems leaves an
    `auth_tokens` row plus a global `users` row - global, so it is keyed on the address rather
    than on the slug, and a `users.username` UNIQUE collision on the second run is what
    forgetting it looks like.
    """
    import shutil
    from pathlib import Path

    from api.database import get_db_path

    async def scrub():
        async with get_system_connection() as conn:
            await conn.execute("DELETE FROM project_registry WHERE slug=?", (SLUG,))
            await conn.execute("DELETE FROM project_memberships WHERE project_slug=?", (SLUG,))
            await conn.execute("DELETE FROM auth_tokens WHERE project_slug=?", (SLUG,))
            await conn.execute("DELETE FROM scheduled_jobs WHERE slug=?", (SLUG,))
            for address in (APPROVER_EMAIL, get_settings().admin_username):
                await conn.execute("DELETE FROM users WHERE username=?", (address,))
                await conn.execute("DELETE FROM auth_tokens WHERE email=?", (address,))
            await conn.commit()
        db = get_db_path(SLUG)
        for suffix in ("", "-wal", "-shm"):
            Path(str(db) + suffix).unlink(missing_ok=True)
        shutil.rmtree(Path(get_settings().projects_dir) / SLUG, ignore_errors=True)

    await scrub()
    yield
    await scrub()


@pytest.fixture
def captured_invites(monkeypatch):
    """The raw invite tokens creation mints, keyed by address.

    Wraps the **real** `issue_invite` rather than replacing it, so the `auth_tokens` row is
    genuinely written and the assertions about it below are about production's own write. The
    token is captured only because `create_project` has no reason to return it: nothing
    delivers an invite in this product, so an operator retrieves it through `resend-invite`.
    This gives the test the same string that door would hand over, without routing every test
    through a second endpoint.

    Patched on `api.services.project_service`, where the name is **looked up**, not on
    `invite_service` where it is defined. `project_service` binds its own reference with `from
    ... import issue_invite`, so patching the definition site would leave this call untouched -
    which is exactly the failure CLAUDE.md records for four crew tests patching
    `get_tools_for_agent`.
    """
    import api.services.project_service as project_service
    from api.services.invite_service import issue_invite as real_issue_invite

    tokens: dict[str, str] = {}

    async def _capturing(*, email: str, project_slug: str, stakeholder_id: int) -> str:
        raw = await real_issue_invite(
            email=email, project_slug=project_slug, stakeholder_id=stakeholder_id
        )
        tokens[email.strip().lower()] = raw
        return raw

    monkeypatch.setattr(project_service, "issue_invite", _capturing)
    return tokens


async def _open_a_gate() -> int:
    """The first HITL gate, in the shape `HumanInputTool` writes it.

    A `human_reviews` row with `decision='pending'` and no `output_id` - see
    `insert_hitl_review` in `agents/tools/_db.py`. Written directly rather than by running a
    crew: the gate is what is under test, not the crew that raises it, and a real run costs
    money and needs a model.
    """
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        cur = await conn.execute(
            "INSERT INTO crew_runs (project_id, crew_name, status) VALUES (?,?,?)",
            (project["id"], "discovery_mapping", "running"),
        )
        cur = await conn.execute(
            "INSERT INTO human_reviews (crew_run_id, decision, prompt) VALUES (?,?,?)",
            (cur.lastrowid, "pending", "Please review the value chain."),
        )
        review_id = cur.lastrowid
        await conn.commit()
    return review_id


async def _approver_rows(email: str = APPROVER_EMAIL) -> list[dict]:
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        rows = await fetch_stakeholders(conn, project_id=project["id"])
    return [r for r in rows if (r.get("email") or "").strip().lower() == email.strip().lower()]


async def _live_invites(email: str = APPROVER_EMAIL) -> list[dict]:
    """The unredeemed invites for this address **on this slug**.

    Scoped to the slug as well as the address deliberately: one login is invited onto many
    engagements, `issue_invite` keeps one live token per `(email, project_slug)`, and a query
    on the address alone would count another engagement's invite as this one's.
    """
    async with get_system_connection() as conn:
        cur = await conn.execute(
            "SELECT id, token_hash, stakeholder_id, expires_at FROM auth_tokens"
            " WHERE email=? AND project_slug=? AND purpose='invite' AND used_at IS NULL",
            (email, SLUG),
        )
        return [dict(r) for r in await cur.fetchall()]


# ── 1. The headline: the gate opens for the person named at creation ──────────


@pytest.mark.asyncio
async def test_the_person_named_at_creation_can_open_the_first_hitl_gate(
    creator, anon, captured_invites
):
    """A project created from nothing, and its first gate resolved by the named approver.

    The whole point of the change, end to end over HTTP, through nothing but shipped doors:
    `POST /projects` with an approver, `POST /auth/accept` to redeem the invite creation
    minted, then `PATCH /projects/{slug}/reviews/{id}` as that person. Nothing is seeded by
    hand except the gate itself.

    **Asserted on the gate resolving, not on a permission flag.** `can_approve` flipping to
    true is one layer away from the property: it is what `caller_may_approve` answers, and the
    defect this closes was never in that function. The row in `human_reviews` is what
    `HumanInputTool` polls, so it is what decides whether a paused crew proceeds - a 200 from
    the door says the request was accepted, not that the crew can carry on.

    The permissions read is kept as well, immediately before, because it is a **witness**
    rather than the claim: if the gate refused, it tells the next reader whether the walk
    failed or the gate did.
    """
    created = await creator.post("/projects", json=_body())
    assert created.status_code == 201, created.text
    review_id = await _open_a_gate()

    # The invite creation minted, redeemed by the person it names. `/auth/accept` takes no
    # authentication, and this is the call that writes the `users` row and the
    # `project_memberships` row - the two steps of the walk a stakeholder row alone cannot
    # supply, and the reason seeding the creator does not work.
    raw = captured_invites[APPROVER_EMAIL]
    redeemed = await anon.post(
        "/auth/accept", json={"token": raw, "password": "a-password-she-chose-1"}
    )
    assert redeemed.status_code == 200, redeemed.text
    session = redeemed.json()["access_token"]
    assert session, (
        "no session was minted, so this address already had a login and the invite was a "
        "membership grant - the premise of this test is a person with no account"
    )

    from api.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {session}"},
    ) as approver:
        perms = await approver.get(f"/projects/{SLUG}/my-permissions")
        assert perms.status_code == 200, perms.text
        assert perms.json()["can_approve"] is True, (
            "the walk did not reach the stakeholder row, so the gate below would fail for a "
            "reason that has nothing to do with the gate"
        )

        resolved = await approver.patch(
            f"/projects/{SLUG}/reviews/{review_id}",
            json={"decision": "approved", "notes": "Happy with this."},
        )

    assert resolved.status_code == 200, resolved.text

    async with get_connection(SLUG) as conn:
        cur = await conn.execute(
            "SELECT decision FROM human_reviews WHERE id=?", (review_id,)
        )
        assert (await cur.fetchone())["decision"] == "approved"


@pytest.mark.asyncio
async def test_the_creator_is_still_refused_on_that_same_gate(creator):
    """The control for the headline test, and it is not a formality.

    Without it, "the gate opened" is consistent with the gate having been widened for
    everybody - which is precisely the cheap repair sp67 declined. The same gate, the same
    project, one caller who was named the approver and one who was not: the first resolves it
    and the second is refused by name.

    Administration is untouched and is asserted here too, because the pair is the point. The
    creator configures the whole engagement and approves none of it.
    """
    assert (await creator.post("/projects", json=_body())).status_code == 201
    review_id = await _open_a_gate()

    perms = await creator.get(f"/projects/{SLUG}/my-permissions")
    assert perms.json()["can_administer_project"] is True
    assert perms.json()["can_approve"] is False

    refused = await creator.patch(
        f"/projects/{SLUG}/reviews/{review_id}",
        json={"decision": "approved", "notes": ""},
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == CONTENT_REFUSAL


# ── 2. Refused without an approver, accepted with one ─────────────────────────


@pytest.mark.parametrize(
    "missing",
    [
        pytest.param(("approver_name", "approver_email"), id="neither"),
        pytest.param(("approver_name",), id="no-name"),
        pytest.param(("approver_email",), id="no-email"),
    ],
)
@pytest.mark.asyncio
async def test_creating_without_an_approver_is_refused_and_says_which_field(creator, missing):
    """422, naming the field that is absent - and creating nothing.

    Both halves matter. The refusal has to name the field because the consultant filling the
    form is the person who has to fix it; and a refused creation must leave no project behind,
    or the next attempt is a re-POST answering 200 and the approver is never written at all.
    Pydantic refuses before `create_project` runs, so the second half is structural rather
    than arranged - asserted anyway, because that is a property of *where* the validation
    sits and a later move of it into the service would break it silently.
    """
    body = {k: v for k, v in _body().items() if k not in missing}

    r = await creator.post("/projects", json=body)
    assert r.status_code == 422, r.text
    reported = {tuple(e["loc"])[-1] for e in r.json()["detail"]}
    assert reported == set(missing), r.text

    from api.database import get_db_path

    assert not get_db_path(SLUG).exists(), "a refused creation left a project database behind"


@pytest.mark.asyncio
async def test_the_control_a_complete_body_is_accepted(creator):
    """The other direction, without which every refusal above is consistent with a door that
    refuses everything. Deliberately a separate test rather than a line in each parametrised
    case, so the count of refusals cannot drift away from the count of acceptances."""
    r = await creator.post("/projects", json=_body())
    assert r.status_code == 201, r.text
    assert r.json()["slug"] == SLUG


@pytest.mark.parametrize(
    "address, accepted",
    [
        pytest.param("rosalind.achebe@client.test", True, id="ordinary"),
        pytest.param("r.a+approvals@sub.client.test", True, id="plus-and-subdomain"),
        pytest.param("  rosalind.achebe@client.test  ", True, id="surrounding-space"),
        pytest.param("", False, id="empty"),
        pytest.param("   ", False, id="whitespace-only"),
        pytest.param("rosalind.achebe", False, id="no-at"),
        pytest.param("rosalind@client", False, id="no-dot-in-domain"),
        pytest.param("rosalind@@client.test", False, id="two-ats"),
        pytest.param("rosalind achebe@client.test", False, id="space-inside"),
        pytest.param("@client.test", False, id="no-local-part"),
        pytest.param("rosalind@.test", False, id="empty-domain-label"),
    ],
)
@pytest.mark.asyncio
async def test_the_approvers_address_is_shape_checked_in_both_directions(
    creator, address, accepted
):
    """Both directions over the door, because a one-sided set of cases passes against a
    validator that accepts everything *or* one that refuses everything.

    A typo'd approver is worse than no approver at all: the stakeholder row exists, the role
    is set, the roster renders, an invite is minted against an address nobody holds - and the
    engagement has a dead end that *looks* closed. Nobody discovers it until a gate has been
    waiting a day.

    This is a **shape** check and nothing more. `rosalind@client.test` passes here whether or
    not `client.test` resolves, and the accepted cases above include a plus-tag and a
    subdomain precisely so that a future tightening cannot quietly refuse addresses real
    people use.
    """
    r = await creator.post("/projects", json=_body(approver_email=address))
    if accepted:
        assert r.status_code == 201, r.text
        # And the address was stored trimmed. Every door that later finds this person -
        # `has_linked_login`, `issue_invite`, `_stakeholder_matches_invite` - matches
        # `users.username` exactly under SQLite's binary collation, so a stored stray space is
        # an address none of them can ever match.
        assert (await _approver_rows(address.strip()))[0]["email"] == address.strip()
    else:
        assert r.status_code == 422, r.text


@pytest.mark.parametrize(
    "name, accepted",
    [
        pytest.param("Rosalind Achebe", True, id="ordinary"),
        pytest.param("  Rosalind Achebe  ", True, id="surrounding-space"),
        pytest.param("", False, id="empty"),
        pytest.param("   ", False, id="spaces-only"),
        pytest.param("\t\n", False, id="tab-and-newline"),
    ],
)
@pytest.mark.asyncio
async def test_the_approvers_name_must_not_be_blank(creator, name, accepted):
    """The name half of the blank check, which nothing else here can reach.

    **This test exists because power-checking found its absence.** Deleting the blank-string
    validator from `ProjectCreate` left every other test in this file green: a blank *address*
    is refused by the shape check regardless, so the two parametrised sets above cover the
    email half twice and the name half not at all. The mutation that removes "required means
    non-blank" was therefore invisible, and a blank name is not cosmetic - every roster, every
    governance notice and the invite itself render it, so an approver with no name is an
    unattributable approval in a client's own correspondence.

    Both directions, and the whitespace cases are separate parameters rather than one, because
    `str.strip()` and a naive `!= ""` differ on exactly them - which is the parser-differential
    shape CLAUDE.md records four instances of.
    """
    r = await creator.post("/projects", json=_body(approver_name=name))
    if accepted:
        assert r.status_code == 201, r.text
        # Stored trimmed, like the address and for a weaker but real reason: the name is
        # rendered, and a leading space is visible in a table cell.
        assert (await _approver_rows())[0]["name"] == name.strip()
    else:
        assert r.status_code == 422, r.text
        assert "cannot be blank" in r.text


def test_the_shape_rule_is_the_one_the_stakeholder_doors_already_enforce():
    """The approver at creation and the same person edited later are held to one rule.

    The scope for this work said there was no email validator anywhere in the product and that
    this would be the first. There were two, already disagreeing: `stakeholder_access.py`'s,
    which the stakeholder write doors enforce, and a second in `interviews.py` with length
    bounds the first does not have. Adding a third would have been the
    `register_scripts_sync` / `scripts_awaiting_regeneration` divergence CLAUDE.md records,
    arriving one more time.

    So this asserts the **identity** of the two, not that each works. Driven as pure functions
    over given strings, in both directions, which is what makes it a test of the rule rather
    than of either caller.
    """
    from api.services.email_shape import looks_like_email
    from api.services.stakeholder_access import has_deliverable_email

    for address in (
        "rosalind.achebe@client.test",
        "r.a+approvals@sub.client.test",
        "",
        "   ",
        "rosalind.achebe",
        "rosalind@client",
        "rosalind achebe@client.test",
    ):
        assert looks_like_email(address) == has_deliverable_email({"email": address}), address


# ── 3. The rows, not the 201 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_creation_writes_a_stakeholder_carrying_is_approver(creator):
    """Asserted on the row, because the 201 is what the defect already produced.

    A creation that answered 201 and wrote nothing is exactly the state being closed, so the
    status code cannot be the evidence. `is_approver` specifically - the flag
    `caller_may_approve` reads - and `is_project_admin` explicitly **not** set, because
    administration and content are separate axes and this field is about the second one. An
    approver who silently also administered the engagement would be a quiet widening of the
    first axis by a change advertised as being about the second.
    """
    assert (await creator.post("/projects", json=_body())).status_code == 201

    rows = await _approver_rows()
    assert len(rows) == 1, f"expected exactly one approver row, got {rows}"
    row = rows[0]
    assert row["name"] == APPROVER_NAME
    assert row["is_approver"] == 1
    assert row["is_project_admin"] == 0, (
        "creation granted administration as well as approval - that is the other axis"
    )
    assert row["is_participant"] == 0


@pytest.mark.asyncio
async def test_creation_issues_one_live_invite_for_that_address_and_slug(creator):
    """The invite row, scoped to the address **and** this slug, pointing at the row created.

    `stakeholder_id` is asserted rather than merely the row's existence: `accept_token` refuses
    an invite whose `stakeholder_id` does not resolve, on its own project, to a stakeholder
    whose email matches the token's. An invite carrying the wrong id is therefore an invite
    that can never be redeemed - a well-formed dead end, which is the failure mode this whole
    change exists to remove.
    """
    assert (await creator.post("/projects", json=_body())).status_code == 201

    invites = await _live_invites()
    assert len(invites) == 1, f"expected exactly one live invite, got {invites}"
    assert invites[0]["stakeholder_id"] == (await _approver_rows())[0]["id"]


@pytest.mark.asyncio
async def test_the_approver_is_not_copied_into_the_stored_configuration(creator):
    """One authority on who approves, and it is the stakeholder row.

    `create_project` writes `req.model_dump()` into both `config.yaml` and `config_json`, and
    the approver is excluded from both. A copy there would be a second answer that no door
    reads and nothing updates - wrong the moment the roster changes - and it would put a
    client's address into the blob `ProjectSettings` round-trips through five call sites, which
    CLAUDE.md records as a hazard of its own.
    """
    import json
    from pathlib import Path

    import yaml

    assert (await creator.post("/projects", json=_body())).status_code == 201

    async with get_connection(SLUG) as conn:
        stored = json.loads((await fetch_project(conn, slug=SLUG))["config_json"])
    on_disk = yaml.safe_load(
        (Path(get_settings().projects_dir) / SLUG / "config.yaml").read_text()
    )

    for blob, where in ((stored, "config_json"), (on_disk, "config.yaml")):
        assert "approver_email" not in blob, f"the approver's address was copied into {where}"
        assert "approver_name" not in blob, f"the approver's name was copied into {where}"
        assert APPROVER_EMAIL not in json.dumps(blob), f"the address reached {where} some other way"


# ── 4. Which half may fail, and which may not ────────────────────────────────


@pytest.mark.asyncio
async def test_a_failed_stakeholder_write_fails_the_creation(creator, monkeypatch):
    """The approver is the reason for this write, so losing it must lose the creation.

    This **inverts** CLAUDE.md's standing rule that a side effect must not veto the thing it is
    a side effect of - the rule that keeps a failed skill proposal from holding a paused crew.
    The approver is not a side effect of creating a project; a creation that succeeded without
    it would answer 201 over precisely the dead end the field was added to close, and would do
    it silently.

    Patched on `project_service`, where the name is looked up.
    """
    import api.services.project_service as project_service

    async def _explode(*a, **kw):
        raise RuntimeError("stakeholders table is unavailable")

    monkeypatch.setattr(project_service, "insert_stakeholder", _explode)

    with pytest.raises(RuntimeError):
        await creator.post("/projects", json=_body())

    assert await _approver_rows() == []
    assert await _live_invites() == []


@pytest.mark.asyncio
async def test_a_creation_that_failed_that_way_is_repaired_by_re_posting(creator, monkeypatch):
    """"Leaves nothing half-built that a re-POST would trip over" - driven, not reasoned.

    The failure above happens *after* the project directory, the database, the project row and
    the milestone schedule are written, so something is certainly left behind. The claim is not
    that nothing is left; it is that what is left is the ordinary "this slug exists" state the
    200 path already handles, and that the re-POST completes the job rather than colliding with
    it. That is the operator's whole recovery procedure: press the button again.
    """
    import api.services.project_service as project_service

    real_insert = project_service.insert_stakeholder
    calls = {"n": 0}

    async def _explode_once(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("stakeholders table is unavailable")
        return await real_insert(*a, **kw)

    monkeypatch.setattr(project_service, "insert_stakeholder", _explode_once)

    with pytest.raises(RuntimeError):
        await creator.post("/projects", json=_body())

    again = await creator.post("/projects", json=_body())
    assert again.status_code == 200, again.text
    assert again.json()["approver"]["created"] is True
    assert len(await _approver_rows()) == 1
    assert len(await _live_invites()) == 1


@pytest.mark.asyncio
async def test_a_failed_invite_does_not_fail_the_creation_and_the_response_says_so(
    creator, monkeypatch
):
    """The other half of the rule, and the response has to carry the bad news.

    Losing the invite costs a recoverable token rather than an engagement: `resend-invite`
    mints a fresh one, which is how the owner was unblocked by hand. Failing the creation for a
    transient `system.db` lock, with everything else already written, is the worse trade in
    both directions.

    **Asserted on what the response tells the consultant**, not only on the 201. A creation
    that quietly succeeded with no invite is a consultant who believes the approver has access
    and finds out otherwise when a gate is already waiting - which is the same class of defect
    as the transcript door answering `{"sent": true}` over a held message.
    """
    import api.services.project_service as project_service

    async def _explode(**kw):
        raise RuntimeError("system database is locked")

    monkeypatch.setattr(project_service, "issue_invite", _explode)

    r = await creator.post("/projects", json=_body())
    assert r.status_code == 201, r.text

    approver = r.json()["approver"]
    assert approver["invited"] is False
    assert "could not be issued" in approver["delivery"]
    assert "Resend invite" in approver["delivery"], (
        "the consultant is told the invite failed but not what to do about it"
    )

    # The half that must not have been lost.
    assert len(await _approver_rows()) == 1
    assert await _live_invites() == []


@pytest.mark.asyncio
async def test_the_successful_response_says_the_invite_is_not_delivered_for_them(creator):
    """What the consultant is told on the ordinary path, and it is deliberately not "sent".

    **Nothing in this product delivers an invite.** `issue_invite` writes an `auth_tokens` row
    and returns the token; no caller passes it to `send_project_mail` or `send_platform_mail`,
    in any mode. The scope for this work expected `dev_mode` to be the thing worth warning
    about - project mail held and redirected to the operator - and `dev_mode` cannot reach a
    path that never sends. A response claiming a redirected email would have been a claim about
    a message nobody sent, which is the exact shape CLAUDE.md's mail section records and calls
    the one to watch for.

    So the sentence says what happened and what to do, and this test pins both halves of it.
    """
    r = await creator.post("/projects", json=_body())
    assert r.status_code == 201, r.text

    approver = r.json()["approver"]
    assert approver["invited"] is True
    assert approver["email"] == APPROVER_EMAIL
    assert "Nothing delivers it automatically" in approver["delivery"]
    assert "Resend invite" in approver["delivery"]


@pytest.mark.asyncio
async def test_creating_a_project_sends_no_mail_at_all(creator, monkeypatch):
    """Established rather than described: nothing on this path reaches Resend.

    The recorder goes on `outbound_mail`'s own `httpx`, which is the module every send path
    goes through and the convention `tests/test_outbound_mail_seam.py` uses. A key is written
    onto the shared settings as well, because `_post_to_resend` raises "not configured" before
    it opens a socket when the key is blank - and a guard that would refuse the send anyway is
    not evidence that no send was attempted. With the key in place, a send would be recorded;
    the assertion is that none is.
    """
    import httpx as real_httpx

    import api.services.outbound_mail as outbound_mail

    requests: list[real_httpx.Request] = []

    def handler(request: real_httpx.Request) -> real_httpx.Response:
        requests.append(request)
        return real_httpx.Response(200, json={"id": "mock-message-id"})

    def factory(*args, **kwargs):
        kwargs["transport"] = real_httpx.MockTransport(handler)
        return real_httpx.AsyncClient(*args, **kwargs)

    monkeypatch.setattr(outbound_mail, "httpx", type(real_httpx)("httpx"))
    monkeypatch.setattr(outbound_mail.httpx, "AsyncClient", factory, raising=False)
    monkeypatch.setattr(get_settings(), "resend_api_key", "re_approver_at_creation_test")

    assert (await creator.post("/projects", json=_body())).status_code == 201

    assert requests == [], f"creation posted to an outbound mail provider: {requests}"


# ── 5. Idempotency ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_re_posting_an_existing_slug_creates_no_second_approver_and_no_second_invite(
    creator,
):
    """The re-POST answers 200 and touches neither the roster nor the token.

    Both halves are asserted, and the second is the one an assertion about the re-POST alone
    cannot make: "no second stakeholder was created" is satisfied perfectly by a creation that
    never created a first, which is CLAUDE.md's "a default and a write are indistinguishable
    until something chooses the other value" in its simplest form. So the first POST's single
    row and single invite are pinned before the second POST happens.

    The invite is compared by `token_hash`. A re-POST that called `issue_invite` again would
    leave exactly one live row - it refreshes rather than inserts - so counting rows cannot see
    it, and the consequence is not cosmetic: refreshing overwrites the hash, so **the link
    already in the approver's hands would stop working**.
    """
    first = await creator.post("/projects", json=_body())
    assert first.status_code == 201, first.text
    assert first.json()["approver"]["created"] is True
    before_rows = await _approver_rows()
    before_invites = await _live_invites()
    assert len(before_rows) == 1 and len(before_invites) == 1

    second = await creator.post("/projects", json=_body())
    assert second.status_code == 200, second.text

    assert [r["id"] for r in await _approver_rows()] == [before_rows[0]["id"]]
    assert await _live_invites() == before_invites, (
        "the re-POST re-issued the invite, which invalidates the link the approver already has"
    )
    assert second.json()["approver"]["created"] is False
    assert "already has this approver" in second.json()["approver"]["delivery"]


@pytest.mark.asyncio
async def test_a_re_post_naming_a_different_approver_does_not_rewrite_the_roster(creator):
    """A re-POST with another name adds that person; it does not replace the first.

    Keyed on the **address**, not on "does this project have an approver yet", and the
    difference is what protects a roster somebody has since edited. A consultant who added a
    second approver, or removed the first and named somebody else, must not have that undone by
    a re-POST - and a creation door is not where a roster is managed. The Stakeholders tab is.
    """
    assert (await creator.post("/projects", json=_body())).status_code == 201
    original = (await _approver_rows())[0]["id"]

    other = "kwame.mensah@client.test"
    try:
        again = await creator.post("/projects", json=_body(approver_email=other,
                                                           approver_name="Kwame Mensah"))
        assert again.status_code == 200, again.text

        assert original in {r["id"] for r in (await _approver_rows(APPROVER_EMAIL))}, (
            "the first approver was removed or overwritten by a re-POST"
        )
        assert len(await _approver_rows(other)) == 1
    finally:
        async with get_system_connection() as conn:
            await conn.execute("DELETE FROM auth_tokens WHERE email=?", (other,))
            await conn.execute("DELETE FROM users WHERE username=?", (other,))
            await conn.commit()


# ── 6. The approver may be the creator ───────────────────────────────────────


@pytest.mark.asyncio
async def test_naming_yourself_as_the_approver_is_accepted_and_not_special_cased(creator):
    """Legitimate and common on a consultancy deployment, and it needs no special handling.

    Worth a test rather than a comment because it is the case somebody would be tempted to
    branch on - "the creator is already here, skip the invite" - and that branch would be
    wrong in the way this whole change is about. The built-in administrator has **no `users`
    row**: `POST /auth/login` matches `ADMIN_USERNAME` before it reads the table. So the row
    the walk starts from does not exist for them either, and the invite is exactly as
    necessary as it is for anybody else.

    The address is the administrator's own configured one, so this is genuinely "the creator
    naming themselves" rather than a second person who happens to be nearby.
    """
    own = f"{get_settings().admin_username}@consultancy.test"

    r = await creator.post("/projects", json=_body(approver_email=own, approver_name="The Consultant"))
    assert r.status_code == 201, r.text

    rows = await _approver_rows(own)
    assert len(rows) == 1 and rows[0]["is_approver"] == 1
    assert len(await _live_invites(own)) == 1, (
        "no invite was issued for the creator - the built-in administrator has no users row, "
        "so without one they have no more content authority than before"
    )

    async with get_system_connection() as conn:
        await conn.execute("DELETE FROM auth_tokens WHERE email=?", (own,))
        await conn.execute("DELETE FROM users WHERE username=?", (own,))
        await conn.commit()
