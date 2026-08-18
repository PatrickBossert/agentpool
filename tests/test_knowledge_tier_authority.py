# tests/test_knowledge_tier_authority.py
"""Write authority follows the tier, and the organisation tier follows the organisation.

Task 2 established *how wide* a caller may write from their login role alone - sector is
sysadmin, organisation is org_admin or above, project is narrower still. That rule is pure
and knows no slug, so it cannot answer the question this module is about: **which**
organisation's store an org_admin may write into.

The distinction is the whole of the risk. `org_{org_slug}` is shared by every project of one
organisation, and on a consultancy deployment the organisations are different clients. An
org_admin permitted "the organisation tier" in the abstract, rather than "their own
organisation's store", would be permitted every client's.

`check_project_access` already refuses an org_admin every slug outside their organisation, so
the boundary is enforced twice on the live doors - the floor first, the tier rule behind it.
That is deliberate and it makes the tier rule's own half hard to witness through a door: the
floor answers first. The tests below therefore do what
`test_an_approver_may_not_promote_material_through_the_chat_door` already does in
tests/test_knowledge_tier_ingestion.py - hold the floor open, so what refuses is the rule
under test and nothing else - and assert the floor separately, on its own.

Every refusal is asserted together with **nothing having been written**: no collection asked
for, and no row in the project's document library. A 403 that has already filed the document
is not a refusal.
"""
import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
    insert_stakeholder,
    insert_user,
    link_membership,
)
from api.services.authority_service import (
    assert_may_write_tier_on_project,
    may_write_tier_on_project,
    writable_tiers_on_project,
)
from api.services.knowledge_tiers import TierWriteRefused

SLUG = "tier-authority"
PROJECT = {
    "client_slug": SLUG,
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.fixture(autouse=True)
def _clean_project():
    """This project's database and files, gone before and after every test.

    `DATABASE_DIR` is a fixed directory that persists between runs (see CLAUDE.md), so a test
    asserting "the document library is empty" would pass once and fail on every run
    afterwards - and, worse, pass or fail depending on which sibling ran first.
    """
    import shutil

    def _wipe():
        settings = get_settings()
        (Path(settings.database_dir) / f"{SLUG}.db").unlink(missing_ok=True)
        shutil.rmtree(Path(settings.projects_dir) / SLUG, ignore_errors=True)

    _wipe()
    yield
    get_settings.cache_clear()
    _wipe()


@pytest.fixture
def chroma():
    """A mocked Chroma, patched where ingest_service looks the factory up."""
    collection = MagicMock()
    client = MagicMock()
    client.get_or_create_collection.return_value = collection
    with patch("api.services.ingest_service.get_chroma_client", return_value=client):
        yield client


def _written_collections(client) -> list[str]:
    """Every collection name this client was asked to write into."""
    return [
        call.args[0] if call.args else call.kwargs["name"]
        for call in client.get_or_create_collection.call_args_list
    ]


async def _library(client) -> list[dict]:
    """This project's document rows, read back through the door that lists them."""
    return (await client.get(f"/projects/{SLUG}/documents")).json()


def _client_with(token: str) -> AsyncClient:
    from api.main import app

    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


def _home_org_collection() -> str:
    """The organisation store `POST /projects` registers a new project into.

    Read from settings rather than written out. tests/conftest.py pins HOME_ORG_SLUG with a
    `setdefault` and says why the tests must not name the literal: an operator who exports
    it in their shell beats the default, and a suite that hardcoded the consultancy's slug
    would go red for them.
    """
    return f"org_{get_settings().home_org_slug}"


async def _home_org_id() -> int:
    """The organisation `POST /projects` registers a new project to."""
    async with get_system_connection() as conn:
        cur = await conn.execute(
            "SELECT id FROM organisations WHERE slug=?", (get_settings().home_org_slug,)
        )
        return (await cur.fetchone())[0]


async def _other_org_id() -> int:
    """A second organisation, and emphatically not the one this project belongs to.

    Inserted directly rather than through `POST /auth/orgs` only because the door is
    sysadmin-only and this is fixture wiring, not the thing under test.
    """
    async with get_system_connection() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO organisations (slug, name) VALUES (?,?)",
            ("rival-consulting", "Rival Consulting"),
        )
        await conn.commit()
        cur = await conn.execute(
            "SELECT id FROM organisations WHERE slug=?", ("rival-consulting",)
        )
        return (await cur.fetchone())[0]


async def _seed_person(*, username: str, email: str, **flags) -> None:
    """A fully wired login: stakeholder row, users row, project membership.

    A caller refused for want of a membership proves nothing about an authority gate, so
    every principal here clears `check_project_access` on its own merits.
    """
    async with get_connection(SLUG) as conn:
        project = await fetch_project(conn, slug=SLUG)
        stakeholder_id = await insert_stakeholder(
            conn, project_id=project["id"], name=username, email=email, **flags
        )
    async with get_system_connection() as sys_conn:
        await insert_user(
            sys_conn, username=username, email=email, role="reviewer", hashed_pw="x"
        )
        user = await fetch_user(sys_conn, username=username)
        await link_membership(
            sys_conn, user_id=user["id"], project_slug=SLUG, stakeholder_id=stakeholder_id
        )


@pytest_asyncio.fixture
async def project(client):
    """The project, created through the API so it is registered to the home organisation."""
    await client.post("/projects", json=PROJECT)
    return SLUG


async def _chat_upload(caller, *, tier=None, name="notes.txt"):
    data = {"agent_name": "Interview Coordinator"}
    if tier is not None:
        data["tier"] = tier
    return await caller.post(
        f"/projects/{SLUG}/agent-chat/upload",
        data=data,
        files={"file": (name, b"the depot runs two shifts", "text/plain")},
    )


async def _documents_upload(caller, *, tier=None, name="report.txt"):
    data = {"tier": tier} if tier is not None else None
    return await caller.post(
        f"/projects/{SLUG}/documents/upload",
        files={"file": (name, io.BytesIO(b"depot capacity notes"), "text/plain")},
        data=data,
    )


# ── The project administrator: their own project's store, and no wider ───────────────────
#
# The chat door rather than the documents door, because the documents door is
# `require_org_admin_or_above` and would refuse a per-project administrator before the tier
# question was ever asked. What is under test here is the tier, so the caller has to reach it.


@pytest_asyncio.fixture
async def project_admin(project):
    """A per-project administrator who is also an approver of this project.

    Both flags, deliberately. `is_project_admin` is the authority the tier table names for
    the project tier; `is_approver` is the chat door's own gate, which sits in front of it.
    Without the second the caller never reaches the tier check and the test would be
    asserting the door's gate under another name.

    **`is_approver` also satisfies the tier rule's own walk**, which is the conflation this
    fixture cannot avoid and must therefore declare: every test using it passes through the
    approver arm whether or not `project_admin` confers anything. The two arms are witnessed
    separately, each alone, by the single-flag tests below - `is_approver` is a convenience
    here and never the thing being proved.
    """
    await _seed_person(
        username="tier-padmin",
        email="padmin@example.com",
        is_project_admin=True,
        is_approver=True,
        is_reviewer=True,
    )
    async with _client_with(create_access_token("tier-padmin", "reviewer", "test-secret")) as c:
        yield c


@pytest_asyncio.fixture
async def project_admin_only(project):
    """A per-project administrator holding `is_project_admin` and no other flag.

    For every door that does not sit behind a content gate. Where one does, the fixture
    above is the only caller that can reach the rule - see its docstring for what that
    costs.
    """
    await _seed_person(
        username="tier-padmin-alone",
        email="padmin-alone@example.com",
        is_project_admin=True,
    )
    token = create_access_token("tier-padmin-alone", "reviewer", "test-secret")
    async with _client_with(token) as c:
        yield c


@pytest.mark.asyncio
async def test_a_project_administrator_may_write_their_own_projects_store(
    client, chroma, project_admin
):
    """The permission half, and it is not decoration: without it every refusal below is
    satisfied by a door that refuses this caller everything.

    Which *arm* of the walk carries this caller is deliberately not what this asserts - the
    fixture holds two flags and either would do. The arms are separated below.
    """
    resp = await _chat_upload(project_admin, tier="project")
    assert resp.status_code == 201
    assert _written_collections(chroma) == [f"{SLUG}_docs"]


# ── The two arms of the project-tier walk, each witnessed alone ──────────────────────────
#
# The rule is `caller_roles(...) & {"project_admin", "approver"}` - a disjunction, and a
# disjunction is only witnessed by a caller who satisfies exactly one side of it. Every test
# above uses a fixture holding both flags, so all of them pass through whichever arm survives
# and none of them can tell that the other was deleted. That is the defect CLAUDE.md opens
# with, in its most ordinary costume: the fixture that names a role also carries the one that
# covers for it.
#
# Asserted at the service rather than through a door, because the doors cannot reach these
# callers: `POST /{slug}/documents/upload` is `require_org_admin_or_above` and the chat door
# needs `caller_may_approve`, so a project administrator holding no other flag is refused by
# a gate in front of the rule. The rule is where the property holds, so the rule is where it
# is asserted.


@pytest.mark.asyncio
async def test_the_project_admin_arm_of_the_walk_carries_a_caller_on_its_own(project):
    """`is_project_admin` and nothing else. Delete the arm and this is the test that says so."""
    await _seed_person(
        username="tier-padmin-only",
        email="padmin-only@example.com",
        is_project_admin=True,
    )
    payload = {"sub": "tier-padmin-only", "role": "reviewer"}
    assert await may_write_tier_on_project(SLUG, "project", payload) is True
    assert await writable_tiers_on_project(SLUG, payload) == ("project",)


@pytest.mark.asyncio
async def test_the_approver_arm_of_the_walk_carries_a_caller_on_its_own(project):
    """`is_approver` and nothing else, so neither arm's coverage stands in for the other's."""
    await _seed_person(
        username="tier-approver-only",
        email="approver-only@example.com",
        is_approver=True,
    )
    payload = {"sub": "tier-approver-only", "role": "reviewer"}
    assert await may_write_tier_on_project(SLUG, "project", payload) is True
    assert await writable_tiers_on_project(SLUG, payload) == ("project",)


@pytest.mark.asyncio
async def test_a_project_administrator_is_refused_the_organisation_tier(
    client, chroma, project_admin
):
    """Administering one engagement is not authority over the organisation's shared store,
    which every sibling project of that organisation reads."""
    resp = await _chat_upload(project_admin, tier="organisation")
    assert resp.status_code == 403
    assert "at the organisation tier" in resp.json()["detail"]
    chroma.get_or_create_collection.assert_not_called()
    assert await _library(client) == []


@pytest.mark.asyncio
async def test_a_project_administrator_is_refused_the_sector_tier(
    client, chroma, project_admin
):
    """Asserted for itself rather than left to the organisation tier's test above. One
    tier's coverage standing in for another's is how this project has been bitten twice."""
    resp = await _chat_upload(project_admin, tier="sector")
    assert resp.status_code == 403
    assert "at the sector tier" in resp.json()["detail"]
    chroma.get_or_create_collection.assert_not_called()
    assert await _library(client) == []


@pytest.mark.asyncio
async def test_a_participant_may_write_no_tier_at_all(client, project):
    """The project tier is authority over *this project*, not "whoever cleared a door".

    A participant clears `check_project_access` - membership is read access by design - and
    is refused by both upload doors' own gates today, so this is defence in depth rather
    than a live hole. It is asserted at the service because that is where the rule lives:
    the third door that forgets a gate is the one this protects against.
    """
    await _seed_person(
        username="tier-participant", email="participant@example.com", is_participant=True
    )
    payload = {"sub": "tier-participant", "role": "reviewer"}
    assert await writable_tiers_on_project(SLUG, payload) == ()
    with pytest.raises(TierWriteRefused):
        await assert_may_write_tier_on_project(SLUG, "project", payload)


# ── The organisation boundary ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def own_org_admin(project):
    """An org_admin of the organisation this project belongs to."""
    token = create_access_token(
        "connie", "org_admin", "test-secret", org_id=await _home_org_id()
    )
    async with _client_with(token) as c:
        yield c


@pytest_asyncio.fixture
async def other_org_admin(project):
    """An org_admin of a *different* organisation from the one this project belongs to."""
    token = create_access_token(
        "rival", "org_admin", "test-secret", org_id=await _other_org_id()
    )
    async with _client_with(token) as c:
        yield c


@pytest.mark.asyncio
async def test_an_org_admin_may_write_their_own_organisations_store(
    client, chroma, own_org_admin
):
    """The control for both refusals below - otherwise 'refused at the organisation tier'
    is satisfied by refusing every org_admin everywhere."""
    resp = await _documents_upload(own_org_admin, tier="organisation")
    assert resp.status_code == 201
    assert _written_collections(chroma) == [_home_org_collection()]


@pytest.mark.asyncio
async def test_an_org_admin_is_refused_the_sector_tier(client, chroma, own_org_admin):
    """A sector store spans different clients on a consultancy deployment, so it takes the
    only role scoped to the whole deployment."""
    resp = await _documents_upload(own_org_admin, tier="sector")
    assert resp.status_code == 403
    assert "at the sector tier" in resp.json()["detail"]
    # The verb fits the door. An upload refused for saying "you may not remove material"
    # would read as a bug in the product, and the two doors below prove the opposite case.
    assert "may not add material" in resp.json()["detail"]
    # The derived half of the sentence, which is computed rather than echoed back from this
    # call - so this assertion fails when the rule is wrong, and not merely when the wording
    # changes. The half above quotes the tier the request named and could not tell a
    # correctly-refused sector request from an incorrectly-refused one.
    assert "you may write: organisation, project." in resp.json()["detail"]
    chroma.get_or_create_collection.assert_not_called()
    assert await _library(client) == []


@pytest.mark.asyncio
async def test_another_organisations_admin_is_refused_this_projects_organisation_tier(
    client, chroma, other_org_admin
):
    """The headline. `check_project_access` refuses this caller the slug outright, so the
    floor is held open here to leave the tier rule as the only thing that can answer - the
    pattern tests/test_knowledge_tier_ingestion.py already uses for the same reason. The
    floor is asserted on its own in the test below.

    Held open on the *router* module, where the name is looked up: the routers bind their
    own reference via `from ... import`, so patching `api.auth` would miss them.
    """
    with patch("api.routers.documents.check_project_access", new=AsyncMock()):
        resp = await _documents_upload(other_org_admin, tier="organisation")
    assert resp.status_code == 403
    assert "at the organisation tier" in resp.json()["detail"]
    chroma.get_or_create_collection.assert_not_called()
    assert await _library(client) == []


@pytest.mark.asyncio
async def test_the_organisation_boundary_holds_in_the_service_not_only_at_the_door(project):
    """The same refusal where the rule actually lives, with no door involved at all.

    `require_writable_tier` is only the translation into a status code; a test that could
    see the rule solely through a router would be the failure mode CLAUDE.md records.
    """
    payload = {"sub": "rival", "role": "org_admin", "org_id": await _other_org_id()}
    with pytest.raises(TierWriteRefused):
        await assert_may_write_tier_on_project(SLUG, "organisation", payload)
    assert await writable_tiers_on_project(SLUG, payload) == ()


@pytest.mark.asyncio
async def test_another_organisations_admin_holds_no_project_tier_here_either(project):
    """The project tier is bounded at the service too, not only by the floor.

    `caller_may_administer_project`'s platform arm reads the login role and never the slug -
    correctly, since its own docstring says it must always be called *after*
    `check_project_access`. This rule does not assume the floor ran, and a door forgetting
    the floor is the single most repeated defect on this codebase (milestones, nonworking
    and pam_report, all in CLAUDE.md). So the boundary the floor would have supplied is
    supplied here as well, and every tier is defended at the service rather than two of the
    three.
    """
    payload = {"sub": "rival", "role": "org_admin", "org_id": await _other_org_id()}
    assert await may_write_tier_on_project(SLUG, "project", payload) is False
    with pytest.raises(TierWriteRefused):
        await assert_may_write_tier_on_project(SLUG, "project", payload)


@pytest.mark.asyncio
async def test_the_projects_own_organisations_admin_still_holds_it(project):
    """The control for the boundary above, at the service and not through a door - so
    'refused' cannot be the answer the project branch gives every org_admin."""
    payload = {"sub": "connie", "role": "org_admin", "org_id": await _home_org_id()}
    assert await may_write_tier_on_project(SLUG, "project", payload) is True


@pytest.mark.asyncio
async def test_a_sysadmin_holds_the_project_tier_of_a_project_belonging_to_no_organisation(
    client
):
    """The bootstrap case, and the one the organisation comparison must not break.

    A project with no `project_registry` row has no organisation for the comparison to
    succeed against, and `POST /auth/login` matches ADMIN_USERNAME before it ever reads
    `users` - so the built-in administrator has no row for the walk either. Both arms empty
    would lock the operator out of the project store of exactly the projects that most need
    an operator.
    """
    await client.post("/projects", json=PROJECT)
    async with get_system_connection() as conn:
        await conn.execute("DELETE FROM project_registry WHERE slug=?", (SLUG,))
        await conn.commit()
    payload = {"sub": "admin", "role": "sysadmin"}
    assert await may_write_tier_on_project(SLUG, "project", payload) is True


@pytest.mark.asyncio
async def test_the_floor_refuses_another_organisations_admin_the_project_entirely(
    client, chroma, other_org_admin
):
    """The other half of the pair above: with `check_project_access` in place this caller
    never reaches the tier question, and the refusal is about the engagement rather than the
    store. Both layers are asserted because a change to either must fail something.
    """
    resp = await _documents_upload(other_org_admin, tier="organisation")
    assert resp.status_code == 403
    assert "project" in resp.json()["detail"].lower()
    chroma.get_or_create_collection.assert_not_called()
    assert await _library(client) == []


@pytest.mark.asyncio
async def test_the_organisation_tier_is_refused_when_the_project_belongs_to_no_organisation(
    client, chroma
):
    """No `project_registry` row is no organisation, and therefore no organisation tier -
    the same answer `collection_for` gives, moved to the door.

    Without it the upload is accepted, the row is filed, and the background ingest fails on
    a project that has already been told its document was stored. A sysadmin drives it
    because the refusal must not be mistakable for "you lack authority": there is no
    destination for anybody.
    """
    await client.post("/projects", json=PROJECT)
    async with get_system_connection() as conn:
        await conn.execute("DELETE FROM project_registry WHERE slug=?", (SLUG,))
        await conn.commit()

    resp = await _documents_upload(client, tier="organisation")
    assert resp.status_code == 422
    # "belongs to no organisation", not "you may not write there" - the phrase a refusal
    # for want of authority uses ("at the organisation tier") must not appear.
    assert "belongs to no organisation" in resp.json()["detail"]
    assert "at the organisation tier" not in resp.json()["detail"]
    chroma.get_or_create_collection.assert_not_called()
    assert await _library(client) == []


@pytest.mark.asyncio
async def test_a_sysadmin_may_write_all_three_tiers(client, chroma, project):
    """One caller, three uploads, three different stores - so no single refusal wired onto
    the door could satisfy this module."""
    for tier, collection in (
        ("project", f"{SLUG}_docs"),
        ("organisation", _home_org_collection()),
        ("sector", "sector_transport"),
    ):
        resp = await _documents_upload(client, tier=tier, name=f"{tier}.txt")
        assert resp.status_code == 201, f"{tier}: {resp.text}"
        assert resp.json()["knowledge_tier"] == tier
    assert _written_collections(chroma) == [
        f"{SLUG}_docs",
        _home_org_collection(),
        "sector_transport",
    ]


# ── Removing material is a write, and the least recoverable one ──────────────────────────
#
# `DELETE /{slug}/documents/{doc_id}` purges the document's chunks from whichever store its
# row names. At the sector tier that store spans different clients on a consultancy
# deployment, so an org_admin of one client destroying material every other client's agents
# retrieve is the same authority asymmetry as an org_admin adding to it - worse, in fact,
# because an addition can be deleted and a deletion cannot be undone.


@pytest.fixture
def delete_chroma():
    """Mocked Chroma patched where the delete door looks it up - inside the handler, off
    `api.services.chroma_client`, which is a different lookup from the ingest path's."""
    collection = MagicMock()
    mocked = MagicMock()
    mocked.get_or_create_collection.return_value = collection
    with patch("api.services.chroma_client.get_chroma_client", return_value=mocked):
        yield mocked


async def _uploaded_and_ingested(client, *, tier) -> int:
    """A document filed at `tier` by a sysadmin, marked ingested so the delete purges."""
    resp = await _documents_upload(client, tier=tier, name=f"{tier}.txt")
    assert resp.status_code == 201, resp.text
    doc_id = resp.json()["id"]
    from api.database import update_document_ingested

    async with get_connection(SLUG) as conn:
        await update_document_ingested(conn, doc_id=doc_id)
    return doc_id


@pytest.mark.asyncio
async def test_an_org_admin_may_not_delete_a_sector_tier_document(
    client, chroma, delete_chroma, own_org_admin
):
    """The sharpest case in the design, in the direction nothing had looked at.

    The refusal is asserted together with the material still being there: the chunks
    unpurged *and* the row still in the library, because a 403 raised after the purge would
    be a refusal that had already done the damage.
    """
    doc_id = await _uploaded_and_ingested(client, tier="sector")
    resp = await own_org_admin.delete(f"/projects/{SLUG}/documents/{doc_id}")
    assert resp.status_code == 403
    assert "at the sector tier" in resp.json()["detail"]
    # The verb, and it is not cosmetic. Patrick will meet this refusal operationally now that
    # a misfiled sector document is a sysadmin's to remove, and being told he may not *add*
    # something he asked to *remove* reads as a bug rather than a refusal.
    assert "may not remove material" in resp.json()["detail"]
    assert "add material" not in resp.json()["detail"]
    delete_chroma.get_or_create_collection.assert_not_called()
    assert [d["id"] for d in await _library(client)] == [doc_id]


@pytest.mark.asyncio
async def test_a_sysadmin_may_delete_a_sector_tier_document(
    client, chroma, delete_chroma, project
):
    """The control. Without it the refusal above is satisfied by a door that deletes
    nothing for anybody."""
    doc_id = await _uploaded_and_ingested(client, tier="sector")
    resp = await client.delete(f"/projects/{SLUG}/documents/{doc_id}")
    assert resp.status_code == 204
    delete_chroma.get_or_create_collection.assert_called_once_with(name="sector_transport")
    assert await _library(client) == []


@pytest.mark.asyncio
async def test_an_org_admin_may_delete_their_own_organisations_document(
    client, chroma, delete_chroma, own_org_admin
):
    """The second control, and the one that keeps the fix from being 'org_admins may delete
    nothing'. Their own organisation's store is theirs to remove from."""
    doc_id = await _uploaded_and_ingested(client, tier="organisation")
    resp = await own_org_admin.delete(f"/projects/{SLUG}/documents/{doc_id}")
    assert resp.status_code == 204
    delete_chroma.get_or_create_collection.assert_called_once_with(
        name=_home_org_collection()
    )


@pytest.mark.asyncio
async def test_an_org_admin_may_not_reingest_a_sector_tier_document(
    client, chroma, own_org_admin
):
    """A reingest re-writes the document's chunks into the same store, so it is a write to
    it by the plainest reading and takes the same authority. Asserted separately from the
    delete because the two doors sit side by side and share nothing but the row.
    """
    doc_id = await _uploaded_and_ingested(client, tier="sector")
    with patch("api.routers.documents.ingest_document", new_callable=AsyncMock) as ingest:
        resp = await own_org_admin.post(f"/projects/{SLUG}/documents/{doc_id}/reingest")
    assert resp.status_code == 403
    assert "at the sector tier" in resp.json()["detail"]
    assert "may not re-index material" in resp.json()["detail"]
    assert "add material" not in resp.json()["detail"]
    ingest.assert_not_called()


# ── /my-permissions answers with the tiers, so the picker need not restate the rule ──────


async def _reported_tiers(caller) -> list[str]:
    resp = await caller.get(f"/projects/{SLUG}/my-permissions")
    assert resp.status_code == 200, resp.text
    return resp.json()["writable_knowledge_tiers"]


@pytest.mark.asyncio
async def test_my_permissions_reports_every_tier_to_a_sysadmin(client, project):
    assert await _reported_tiers(client) == ["sector", "organisation", "project"]


@pytest.mark.asyncio
async def test_my_permissions_reports_no_sector_to_an_org_admin(client, own_org_admin):
    """Broadest first, and the sector is simply absent rather than present-and-refused: a
    control that 403s on submit is worse than one that is not there."""
    assert await _reported_tiers(own_org_admin) == ["organisation", "project"]


@pytest.mark.asyncio
async def test_my_permissions_reports_only_the_project_tier_to_a_project_administrator(
    client, project_admin_only
):
    """The single-flag caller, not the two-flag one beside it. `/my-permissions` needs no
    content gate to reach, so nothing forces the conflation here - and a test named for a
    role should be carried by that role."""
    assert await _reported_tiers(project_admin_only) == ["project"]


@pytest.mark.asyncio
async def test_my_permissions_answers_the_same_rule_the_upload_door_enforces(
    client, chroma, project_admin
):
    """The point of answering here at all. An answer that drifted from the door would put a
    tier in front of somebody it refuses - `is_org_admin_or_above` carries the same note.

    So the reported list is checked against the doors themselves, tier by tier, rather than
    against a second statement of the rule in the test.
    """
    reported = await _reported_tiers(project_admin)
    for tier in ("sector", "organisation", "project"):
        resp = await _chat_upload(project_admin, tier=tier, name=f"{tier}.txt")
        assert (resp.status_code == 201) == (tier in reported), (
            f"/my-permissions and the upload door disagree about {tier}"
        )


@pytest.mark.asyncio
async def test_the_reported_tiers_are_project_scoped_not_merely_role_scoped(
    client, other_org_admin
):
    """An org_admin's login role says `organisation`; on *this* project, which belongs to
    another organisation, the honest answer is that they may not write it.

    Reads the service directly, since the endpoint's own floor refuses this caller the slug -
    which is the correct behaviour and is asserted above.
    """
    payload = {"sub": "rival", "role": "org_admin", "org_id": await _other_org_id()}
    from api.services.knowledge_tiers import writable_tiers

    assert writable_tiers(payload) == ("organisation", "project")
    assert await writable_tiers_on_project(SLUG, payload) == ()
