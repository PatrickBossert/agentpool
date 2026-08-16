# tests/test_account_administration_authority.py
"""Who may administer whose account - asked once, and asked by all three doors.

`PATCH /auth/users/{id}`, `DELETE /auth/users/{id}`, and `POST /auth/users/{id}/reset-link`
are all `require_org_admin_or_above`, and the tier is the wrong question on its own: it says
what kind of caller this is, never whose account they are reaching for.

The gap this file closes was live on master. `svc_update_user`'s guard tested the role being
*granted* - "an org_admin may not grant sysadmin" - and never the account being *edited*. So
an org_admin could PATCH an existing sysadmin with `role="org_admin"` and a password of their
own choosing: the guard did not fire, because the role being granted was not sysadmin. The
platform administrator demoted and their login taken, in one request. `svc_delete_user` asked
nothing about its target at all.

Every test here therefore proves the *write did not happen*, not merely that the response was
a 409. A status code is one layer away from the property - a handler that refused after
committing would satisfy it perfectly - so the target's old password is carried to
`/auth/login` afterwards, which is where a seized account would show itself.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from api.auth import create_access_token, hash_password
from api.config import get_settings
from api.database import (
    get_system_connection, fetch_user, insert_organisation, insert_org_membership, insert_user,
)

_JWT_SECRET = "test-secret"  # conftest.py's os.environ.setdefault - never overridden here


async def _client():
    from api.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_login(username: str, password: str, role: str, org_id: int | None) -> int:
    async with get_system_connection() as conn:
        await insert_user(
            conn, username=username, email=username, role=role,
            hashed_pw=hash_password(password),
        )
        user = await fetch_user(conn, username=username)
        if org_id is not None:
            await insert_org_membership(
                conn, user_id=user["id"], org_id=org_id,
                role="org_admin" if role == "org_admin" else "member",
            )
    return user["id"]


@pytest_asyncio.fixture
async def two_organisations(tmp_path, monkeypatch):
    """Its own DATABASE_DIR per CLAUDE.md's persistent-database trap - every test here writes
    users rows keyed by name, and the shared /tmp/agentpool_test survives between runs.

    An org_admin of Acme, and three accounts they might reach for: the platform sysadmin, a
    colleague inside Acme, and somebody in another organisation entirely.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()

    async with get_system_connection() as conn:
        acme = await insert_organisation(conn, slug="acme", name="Acme")
        other = await insert_organisation(conn, slug="other", name="Other")

    ids = {
        "caller": await _make_login("boss@acme.test", "boss-pw", "org_admin", acme),
        # A member of Acme, and load-bearing that they are: with no organisation the
        # *other-organisation* condition would refuse this account too, and every assertion
        # below about a sysadmin target would pass with the sysadmin condition deleted. It
        # did - a power check caught it. A platform administrator sitting inside a client
        # organisation is also the realistic arrangement.
        "root": await _make_login("root@platform.test", "roots-own-password", "sysadmin", acme),
        "colleague": await _make_login("colleague@acme.test", "colleagues-own-password",
                                       "reviewer", acme),
        "outsider": await _make_login("outsider@other.test", "outsiders-own-password",
                                      "reviewer", other),
    }
    yield {
        **ids,
        "acme": acme,
        "other": other,
        "org_admin": create_access_token("boss@acme.test", "org_admin", _JWT_SECRET,
                                          org_id=acme),
        "sysadmin": create_access_token("root@platform.test", "sysadmin", _JWT_SECRET),
    }
    get_settings.cache_clear()


async def _still_signs_in(ac, username: str, password: str) -> bool:
    resp = await ac.post("/auth/login", data={"username": username, "password": password})
    return resp.status_code == 200


# ── The takeover the role guard could not see ────────────────────────────────

@pytest.mark.asyncio
async def test_an_org_admin_cannot_demote_a_sysadmin_and_take_their_login(two_organisations):
    """The exact request that was live on master: role="org_admin" (not sysadmin, so the old
    guard stayed quiet) and a password of the caller's choosing."""
    async with await _client() as ac:
        resp = await ac.patch(
            f"/auth/users/{two_organisations['root']}",
            json={
                "email": "root@platform.test",
                "role": "org_admin",
                "password": "chosen-by-the-attacker",
            },
            headers=_auth(two_organisations["org_admin"]),
        )
        assert resp.status_code == 409

        # The half a status code cannot see. A refusal raised after the UPDATE would leave
        # the account seized and this test green.
        assert await _still_signs_in(ac, "root@platform.test", "roots-own-password")
        assert not await _still_signs_in(ac, "root@platform.test", "chosen-by-the-attacker")

    # And the demotion did not land either - the role is what carries is_sys_admin into
    # caller_roles, so a successful demotion would strip authority everywhere at once.
    async with get_system_connection() as conn:
        row = await fetch_user(conn, username="root@platform.test")
    assert row["role"] == "sysadmin"


@pytest.mark.asyncio
async def test_an_org_admin_cannot_edit_an_account_in_another_organisation(two_organisations):
    async with await _client() as ac:
        resp = await ac.patch(
            f"/auth/users/{two_organisations['outsider']}",
            json={
                "email": "outsider@other.test",
                "role": "reviewer",
                "password": "chosen-by-the-attacker",
            },
            headers=_auth(two_organisations["org_admin"]),
        )
        assert resp.status_code == 409
        assert await _still_signs_in(ac, "outsider@other.test", "outsiders-own-password")
        assert not await _still_signs_in(ac, "outsider@other.test", "chosen-by-the-attacker")


@pytest.mark.asyncio
async def test_an_org_admin_cannot_delete_a_sysadmin(two_organisations):
    """The same gap, one field shorter to exploit: DELETE took no calling payload at all."""
    async with await _client() as ac:
        resp = await ac.delete(
            f"/auth/users/{two_organisations['root']}",
            headers=_auth(two_organisations["org_admin"]),
        )
        assert resp.status_code == 409
        assert await _still_signs_in(ac, "root@platform.test", "roots-own-password")

    async with get_system_connection() as conn:
        assert await fetch_user(conn, username="root@platform.test") is not None


@pytest.mark.asyncio
async def test_an_org_admin_cannot_delete_an_account_in_another_organisation(two_organisations):
    async with await _client() as ac:
        resp = await ac.delete(
            f"/auth/users/{two_organisations['outsider']}",
            headers=_auth(two_organisations["org_admin"]),
        )
        assert resp.status_code == 409
        assert await _still_signs_in(ac, "outsider@other.test", "outsiders-own-password")


# ── One question, asked by every door ────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["root", "outsider"])
async def test_all_three_account_doors_answer_identically(two_organisations, target):
    """The extraction, asserted rather than assumed.

    A guard copied per door is a guard that will be right on some doors and wrong on others -
    this project already carries two copies of a WHERE clause that have diverged. All three
    doors call `_assert_may_administer`, so all three must refuse the same target with the
    same status and the same sentence, and any one of them dropping that call fails here.

    It does **not** catch a *fourth* door, and an earlier version of this docstring claimed it
    did. The three requests below are written out by hand, so a door added later is invisible
    to this test until somebody adds it here too. Nothing enforces that mechanically - the
    honest statement of the guarantee is "these three agree", not "every door must".

    The wording is compared as well as the status, because the two refusals must not be told
    apart either: "that is a sysadmin" and "that account belongs to another organisation" are
    both facts about an account this caller is not entitled to read.
    """
    user_id = two_organisations[target]
    headers = _auth(two_organisations["org_admin"])

    async with await _client() as ac:
        answers = [
            await ac.post(f"/auth/users/{user_id}/reset-link", headers=headers),
            await ac.patch(
                f"/auth/users/{user_id}",
                json={"email": "x@example.test", "role": "reviewer", "password": "x-pw"},
                headers=headers,
            ),
            await ac.delete(f"/auth/users/{user_id}", headers=headers),
        ]

    assert [r.status_code for r in answers] == [409, 409, 409]
    details = {r.json()["detail"] for r in answers}
    assert len(details) == 1, f"the three doors must refuse in one voice - got {details}"


@pytest.mark.asyncio
async def test_the_two_refusals_are_worded_alike(two_organisations):
    """A sysadmin target and an other-organisation target must be indistinguishable. Told
    apart, they tell an org_admin which accounts hold the platform role and which belong to
    somebody else's engagement - both by enumerating ids."""
    headers = _auth(two_organisations["org_admin"])
    async with await _client() as ac:
        a = await ac.delete(f"/auth/users/{two_organisations['root']}", headers=headers)
        b = await ac.delete(f"/auth/users/{two_organisations['outsider']}", headers=headers)

    assert a.status_code == b.status_code
    assert a.json() == b.json()


# ── The guard is a scope, not a blanket refusal ──────────────────────────────

@pytest.mark.asyncio
async def test_an_org_admin_still_administers_their_own_organisation(two_organisations):
    """A refusal wired unconditionally onto these doors would close the finding and break
    ordinary administration - which is how a guard gets reverted six weeks later."""
    async with await _client() as ac:
        edited = await ac.patch(
            f"/auth/users/{two_organisations['colleague']}",
            json={
                "email": "colleague@acme.test",
                "role": "reviewer",
                "password": "reset-by-their-own-admin",
            },
            headers=_auth(two_organisations["org_admin"]),
        )
        assert edited.status_code == 200
        # The write really happened - not merely a 200 over an untouched row.
        assert await _still_signs_in(ac, "colleague@acme.test", "reset-by-their-own-admin")

        removed = await ac.delete(
            f"/auth/users/{two_organisations['colleague']}",
            headers=_auth(two_organisations["org_admin"]),
        )
        assert removed.status_code == 204
        assert not await _still_signs_in(ac, "colleague@acme.test", "reset-by-their-own-admin")


@pytest.mark.asyncio
async def test_a_sysadmin_still_administers_across_organisations(two_organisations):
    """Administering across organisations is a sysadmin capability throughout this router,
    and the scope must not have quietly become a rule about everybody."""
    async with await _client() as ac:
        edited = await ac.patch(
            f"/auth/users/{two_organisations['outsider']}",
            json={
                "email": "outsider@other.test",
                "role": "reviewer",
                "password": "set-by-the-platform-admin",
            },
            headers=_auth(two_organisations["sysadmin"]),
        )
        assert edited.status_code == 200
        assert await _still_signs_in(ac, "outsider@other.test", "set-by-the-platform-admin")

        removed = await ac.delete(
            f"/auth/users/{two_organisations['outsider']}",
            headers=_auth(two_organisations["sysadmin"]),
        )
        assert removed.status_code == 204
        assert not await _still_signs_in(ac, "outsider@other.test", "set-by-the-platform-admin")


# ── The premise the guard rests on ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_organisation_answer_cannot_be_rewritten_on_the_way_past(two_organisations):
    """The whole chain, because the defect is not visible in any single request.

    `_assert_may_administer` decides "is this account in my organisation?" by reading
    `org_memberships` - and `POST`/`DELETE /auth/orgs/{org_id}/members` are the doors that
    write it. Both took `org_id` from the path and compared it to nothing, so an org_admin
    refused at step 0 could make the answer yes and come back. Every request in this chain is
    at the caller's own tier; not one of them is an escalation on its own.

    Driven end to end and asserted on the *outcome*, not on the membership doors' status
    codes: a test that checked step 1 returned 403 would still pass if step 2 let the account
    in by another route, and the property that matters is that the takeover does not happen.
    """
    outsider = two_organisations["outsider"]
    headers = _auth(two_organisations["org_admin"])

    async with await _client() as ac:
        step0 = await ac.patch(
            f"/auth/users/{outsider}",
            json={"email": "outsider@other.test", "role": "reviewer", "password": "seized"},
            headers=headers,
        )
        assert step0.status_code == 409, "the account door must refuse before the chain starts"

        # Steps 1 and 2: rewrite the premise. They are refused for different reasons, and
        # both refusals are needed - scoping step 1 alone leaves step 2 able to *claim* the
        # account without moving it, since a membership in the caller's organisation is all
        # the guard was looking for.
        step1 = await ac.delete(
            f"/auth/orgs/{two_organisations['other']}/members/{outsider}", headers=headers
        )
        assert step1.status_code == 403, "removing another organisation's membership"

        step2 = await ac.post(
            f"/auth/orgs/{two_organisations['acme']}/members",
            json={"user_id": outsider, "role": "member"},
            headers=headers,
        )
        assert step2.status_code == 409, "claiming an account another organisation holds"

        # Step 3: back to the account door, which must still refuse.
        step3 = await ac.patch(
            f"/auth/users/{outsider}",
            json={"email": "outsider@other.test", "role": "reviewer", "password": "seized"},
            headers=headers,
        )
        assert step3.status_code == 409

        # Step 4: the only assertion that cannot be satisfied by a chain that half-worked.
        assert await _still_signs_in(ac, "outsider@other.test", "outsiders-own-password")
        assert not await _still_signs_in(ac, "outsider@other.test", "seized")


@pytest.mark.asyncio
async def test_a_shared_account_is_administrable_by_neither_organisation(two_organisations):
    """An account in two organisations belongs to neither org_admin.

    Only a sysadmin can produce this state now, and it is a legitimate one to produce - but
    the guard used to read the *first* membership row, so whichever organisation's row sorted
    first would have got a free hand over an account the other one also holds. The rule is
    unanimity: every membership in the caller's organisation, or the account is not theirs.
    Set up through the sysadmin's own door rather than by writing the table directly, so the
    state under test is one the API can really reach.
    """
    outsider = two_organisations["outsider"]
    async with await _client() as ac:
        shared = await ac.post(
            f"/auth/orgs/{two_organisations['acme']}/members",
            json={"user_id": outsider, "role": "member"},
            headers=_auth(two_organisations["sysadmin"]),
        )
        assert shared.status_code == 201

        # Acme now holds a membership on this account, and it is still not Acme's to touch.
        refused = await ac.patch(
            f"/auth/users/{outsider}",
            json={"email": "outsider@other.test", "role": "reviewer", "password": "seized"},
            headers=_auth(two_organisations["org_admin"]),
        )
        assert refused.status_code == 409
        assert await _still_signs_in(ac, "outsider@other.test", "outsiders-own-password")
        assert not await _still_signs_in(ac, "outsider@other.test", "seized")


@pytest.mark.asyncio
async def test_the_membership_doors_still_work_inside_the_callers_own_organisation(
    two_organisations,
):
    """The scope is a scope. An org_admin runs their own organisation's membership - adding a
    colleague, changing their role, removing them - and a guard that refused all three would
    close the chain by breaking the feature."""
    headers = _auth(two_organisations["org_admin"])
    acme = two_organisations["acme"]
    # Somebody with no organisation yet, so the add is a real add.
    newcomer = await _make_login("newcomer@acme.test", "newcomers-pw", "reviewer", None)

    async with await _client() as ac:
        added = await ac.post(
            f"/auth/orgs/{acme}/members",
            json={"user_id": newcomer, "role": "member"},
            headers=headers,
        )
        assert added.status_code == 201

        # And the membership really landed: the account door now agrees they are ours.
        reachable = await ac.post(f"/auth/users/{newcomer}/reset-link", headers=headers)
        assert reachable.status_code == 200

        changed = await ac.patch(
            f"/auth/orgs/{acme}/members/{newcomer}", json={"role": "member"}, headers=headers
        )
        assert changed.status_code == 200

        removed = await ac.delete(f"/auth/orgs/{acme}/members/{newcomer}", headers=headers)
        assert removed.status_code == 204


@pytest.mark.asyncio
async def test_a_sysadmin_still_moves_accounts_between_organisations(two_organisations):
    """Membership administration across organisations stays a sysadmin capability."""
    headers = _auth(two_organisations["sysadmin"])
    outsider = two_organisations["outsider"]

    async with await _client() as ac:
        removed = await ac.delete(
            f"/auth/orgs/{two_organisations['other']}/members/{outsider}", headers=headers
        )
        assert removed.status_code == 204
        added = await ac.post(
            f"/auth/orgs/{two_organisations['acme']}/members",
            json={"user_id": outsider, "role": "member"},
            headers=headers,
        )
        assert added.status_code == 201


# ── The tier below the doors ─────────────────────────────────────────────────

@pytest_asyncio.fixture
async def below_the_tier(two_organisations):
    """A plain reviewer login, and a reviewer who is an approver on a project.

    The approver is the case worth naming: they hold a project role that lets them approve an
    engagement's outputs, and `caller_roles` would say so - but administering a login is not
    project content, so the project role must buy nothing on these doors.
    """
    from api.database import (
        get_connection, insert_project, fetch_project, insert_stakeholder, link_membership,
    )
    slug = "authority-project"
    async with get_connection(slug) as conn:
        await insert_project(conn, slug=slug, llm_mode="standard", sector="", config_json="{}")
        project = await fetch_project(conn, slug=slug)
        sid = await insert_stakeholder(
            conn, project_id=project["id"], name="Ada", email="ada@acme.test",
            is_reviewer=True, is_approver=True,
        )
    approver_id = await _make_login("ada@acme.test", "adas-pw", "reviewer", None)
    await _make_login("plain@acme.test", "plains-pw", "reviewer", None)
    async with get_system_connection() as conn:
        await link_membership(
            conn, user_id=approver_id, project_slug=slug, stakeholder_id=sid
        )
    return {
        "reviewer": create_access_token("plain@acme.test", "reviewer", _JWT_SECRET),
        "approver": create_access_token("ada@acme.test", "reviewer", _JWT_SECRET),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["reviewer", "approver"])
async def test_editing_an_account_refuses_below_the_platform_tier(
    two_organisations, below_the_tier, who
):
    """`update_user_endpoint`'s signature was edited on this branch and nothing witnessed its
    gate: downgrading it to require_any_auth left the whole suite green, with a plain reviewer
    able to set any account's password."""
    target = two_organisations["colleague"]
    async with await _client() as ac:
        resp = await ac.patch(
            f"/auth/users/{target}",
            json={"email": "colleague@acme.test", "role": "reviewer", "password": "seized"},
            headers=_auth(below_the_tier[who]),
        )
        assert resp.status_code == 403, f"{who} must not be able to edit an account"
        assert await _still_signs_in(ac, "colleague@acme.test", "colleagues-own-password")
        assert not await _still_signs_in(ac, "colleague@acme.test", "seized")


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["reviewer", "approver"])
async def test_deleting_an_account_refuses_below_the_platform_tier(
    two_organisations, below_the_tier, who
):
    """The dependency moved from the decorator into the signature on this branch, which is
    exactly the edit that can drop a gate without anything noticing."""
    target = two_organisations["colleague"]
    async with await _client() as ac:
        resp = await ac.delete(f"/auth/users/{target}", headers=_auth(below_the_tier[who]))
        assert resp.status_code == 403, f"{who} must not be able to delete an account"
        assert await _still_signs_in(ac, "colleague@acme.test", "colleagues-own-password")


@pytest.mark.asyncio
async def test_a_missing_account_is_still_a_404_on_both_doors(two_organisations):
    """The refusal has to be told apart from a target that was never there, or the tests
    above would pass just as well against a guard that refused everything, or against one
    that never found its user."""
    async with await _client() as ac:
        patched = await ac.patch(
            "/auth/users/98765",
            json={"email": "nobody@example.test", "role": "reviewer"},
            headers=_auth(two_organisations["sysadmin"]),
        )
        deleted = await ac.delete(
            "/auth/users/98765", headers=_auth(two_organisations["sysadmin"])
        )
    assert patched.status_code == 404
    assert deleted.status_code == 404
