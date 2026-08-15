"""An org_admin reaches an engagement because a registry row says the organisation owns it.

`check_project_access` asks the right question and always did. What was missing was the data:
`project_registry` and `organisations` both held zero rows on the live deployment, and project
creation only wrote a registry row when the creator's role was `org_admin` - while a sysadmin's
token, which is what created everything, carries no `org_id` at all. The gate made the hole
permanent, because the only role that would have produced rows was the one it locked out.

Nothing about it was visible: with a single sysadmin account, `check_project_access` returns
before the registry is consulted, and `project_memberships` - the table a diagnosis would have
gone to - looks perfectly correct throughout.

So every test here drives the property over HTTP, through a door that calls
`check_project_access`, with a real `org_admin` token. `GET /projects/{slug}/status` is the door
chosen: `require_any_auth` then `check_project_access`, so an org_admin clears the role
dependency on its login role alone and every refusal it receives is attributable to the registry
and to nothing else. Refusals are asserted on `detail` as well as status for the same reason.

Asserting on `project_registry` rows would prove nothing - a row is one layer away from the
access it is supposed to confer, which is the failure this project keeps hitting. Where a row is
asserted at all below it is *in addition to* the reachability assertion, never instead of it.
"""
import shutil
import sqlite3

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.auth import create_access_token
from api.config import get_settings
from api.database import (
    delete_project_registry,
    fetch_organisation_by_slug,
    fetch_project_registry,
    get_system_connection,
    insert_organisation,
    insert_project_registry,
    resolve_home_org_id,
)
from scripts.backfill_project_registry import BackfillRefused, backfill_project_registry

ACCESS_DENIED = "Access denied to this project"


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


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """DATABASE_DIR and PROJECTS_DIR at this test's own tmp_path.

    `system.db` - which holds `organisations` and `project_registry` - otherwise lives at the
    shared, persistent /tmp/agentpool_test, and every test in here inserts against fixed slugs.
    That is the trap CLAUDE.md documents: it would pass once and fail on every run afterwards.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


# ── The organisation exists at all ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_home_organisation_is_seeded_by_init_system_db(isolated_dirs):
    """Zero organisations is the state the deployment was actually in.

    Seeding is in `init_system_db` rather than in the backfill script or a runbook step
    precisely because the defect was self-reinforcing - nothing created the data and nothing
    ever would. A fix that waits for somebody to remember re-creates the hole on the next
    fresh deployment, so this asserts that merely opening the system database is enough.

    Read from the settings, not written as "future-edge"/"Future Edge Consulting". The whole
    reason these are settings is that a fork or a renamed deployment can be itself, and a
    literal here would mean such a deployment could not run its own suite.
    """
    settings = get_settings()
    async with get_system_connection() as conn:
        org = await fetch_organisation_by_slug(conn, slug=settings.home_org_slug)
        assert org is not None, "a fresh system database has no home organisation"
        assert org["name"] == settings.home_org_name
        assert await resolve_home_org_id(conn) == org["id"]


@pytest.mark.asyncio
async def test_home_org_resolution_follows_the_slug_and_nothing_else(
    isolated_dirs, monkeypatch
):
    """Resolution is by slug, never by 'the only row', 'the first row', or the lowest id.

    A second organisation created through POST /auth/orgs must not change which organisation
    new projects are registered to - the wrong answer here hands an unrelated organisation's
    admin a real engagement, which is worse than failing to register at all.

    Both halves are needed. The seeded home organisation is always the *lowest* id, so a
    resolver that simply took `ORDER BY id LIMIT 1` would satisfy the first assertion by
    coincidence. The second moves the configured slug onto the higher-id organisation, which
    only a slug lookup can follow.
    """
    async with get_system_connection() as conn:
        home = await resolve_home_org_id(conn)
        other = await insert_organisation(conn, slug="acme", name="Acme Ltd")
        assert other > home, "acme must be the higher id for the second half to bite"
        assert await resolve_home_org_id(conn) == home

    monkeypatch.setenv("HOME_ORG_SLUG", "acme")
    get_settings.cache_clear()
    async with get_system_connection() as conn:
        assert await resolve_home_org_id(conn) == other


# ── The property itself: a registry row is what confers access ────────────────


@pytest_asyncio.fixture
async def access_doors(isolated_dirs):
    """Two real projects, one registered to the home organisation and one not.

    Both registry rows are deleted after creation and exactly one is written back, so the only
    difference between the two calls below is the row - not the project, not the caller, not
    the door.
    """
    sysadmin = _client_for("registry-sysadmin", "sysadmin")
    async with sysadmin:
        for slug in ("registry-alpha", "registry-beta"):
            r = await sysadmin.post("/projects", json=_project_body(slug))
            assert r.status_code in (200, 201), r.text

    async with get_system_connection() as conn:
        home = await resolve_home_org_id(conn)
        await delete_project_registry(conn, slug="registry-alpha")
        await delete_project_registry(conn, slug="registry-beta")
        await insert_project_registry(
            conn, slug="registry-alpha", org_id=home, display_name="registry-alpha"
        )

    admin = _client_for("registry-admin", "org_admin", org_id=home)
    async with admin:
        yield admin


@pytest.mark.asyncio
async def test_org_admin_reaches_a_project_its_organisation_owns(access_doors):
    r = await access_doors.get("/projects/registry-alpha/status")
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_the_same_org_admin_is_refused_on_an_unregistered_slug(access_doors):
    """The control for the test above - same token, same door, no registry row."""
    r = await access_doors.get("/projects/registry-beta/status")
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == ACCESS_DENIED


# ── Creation registers, whatever the creator's role ───────────────────────────


@pytest.mark.asyncio
async def test_a_project_created_by_a_sysadmin_is_reachable_by_an_org_admin(isolated_dirs):
    """Driven through POST /projects, and asserted by an org_admin walking through a door.

    A sysadmin creating the project is the whole case: their token carries no `org_id`, which
    is exactly why the old `role == "org_admin"` condition produced nothing on a deployment
    where the sysadmin creates everything.
    """
    sysadmin = _client_for("create-sysadmin", "sysadmin")
    async with sysadmin:
        r = await sysadmin.post("/projects", json=_project_body("registry-created"))
        assert r.status_code in (200, 201), r.text

    async with get_system_connection() as conn:
        home = await resolve_home_org_id(conn)

    # The door first, and deliberately so: a registry row is one layer away from the access it
    # confers, and asserting the row before the call would let the row's absence mask whether
    # the access assertion can fail at all.
    admin = _client_for("create-admin", "org_admin", org_id=home)
    async with admin:
        r = await admin.get("/projects/registry-created/status")
    assert r.status_code == 200, r.text

    async with get_system_connection() as conn:
        row = await fetch_project_registry(conn, slug="registry-created")
    assert row is not None and row["org_id"] == home


@pytest.mark.asyncio
async def test_creation_resolves_the_home_organisation_by_slug_not_by_lowest_id(
    isolated_dirs, monkeypatch
):
    """The endpoint's resolver, not the helper's - and they are different properties.

    `test_home_org_resolution_follows_the_slug_and_nothing_else` pins `resolve_home_org_id`.
    Nothing pinned that `POST /projects` *calls* it: the seeded home organisation is always the
    lowest id in a fresh database, so an inline `SELECT id FROM organisations ORDER BY id
    LIMIT 1` at the endpoint agrees with the helper on every other test in this file and the
    whole suite stays green. That is CLAUDE.md's canonical failure - `check_write` tested, the
    tool calling it not - and it is the same coincidence already caught once at the helper.

    What it would permit is not hypothetical: a system database holding an organisation created
    ahead of the seed hands every sysadmin-created project to that organisation's admins.

    So the home organisation here is deliberately the *higher* id. Lowest-id and by-slug give
    different answers, and only the by-slug answer lets `higher` through and refuses `lower`.
    """
    async with get_system_connection() as conn:
        lower = await resolve_home_org_id(conn)          # the seeded default, id 1
        higher = await insert_organisation(conn, slug="later-consultancy", name="Later Ltd")
    assert higher > lower, "the fixture only bites if the new organisation has the higher id"

    monkeypatch.setenv("HOME_ORG_SLUG", "later-consultancy")
    get_settings.cache_clear()

    sysadmin = _client_for("slugres-sysadmin", "sysadmin")
    async with sysadmin:
        r = await sysadmin.post("/projects", json=_project_body("registry-slugres"))
        assert r.status_code in (200, 201), r.text

    higher_admin = _client_for("slugres-higher", "org_admin", org_id=higher)
    lower_admin = _client_for("slugres-lower", "org_admin", org_id=lower)
    async with higher_admin, lower_admin:
        r = await higher_admin.get("/projects/registry-slugres/status")
        assert r.status_code == 200, (
            "the endpoint did not register to the organisation HOME_ORG_SLUG names: " + r.text
        )
        r = await lower_admin.get("/projects/registry-slugres/status")
        assert r.status_code == 403, (
            "the endpoint registered to the lowest-id organisation instead: " + r.text
        )
        assert r.json()["detail"] == ACCESS_DENIED


@pytest.mark.asyncio
async def test_an_org_admin_creating_a_project_keeps_it_in_their_own_organisation(
    isolated_dirs,
):
    """The creator's own organisation wins over the home organisation when the token names one.

    Otherwise an org_admin of another organisation would create a project and immediately be
    refused on it.
    """
    async with get_system_connection() as conn:
        acme = await insert_organisation(conn, slug="acme", name="Acme Ltd")
        home = await resolve_home_org_id(conn)

    admin = _client_for("acme-admin", "org_admin", org_id=acme)
    async with admin:
        r = await admin.post("/projects", json=_project_body("registry-acme"))
        assert r.status_code in (200, 201), r.text
        r = await admin.get("/projects/registry-acme/status")
        assert r.status_code == 200, r.text

    async with get_system_connection() as conn:
        row = await fetch_project_registry(conn, slug="registry-acme")
    assert row["org_id"] == acme != home


@pytest.mark.asyncio
async def test_an_operator_can_still_move_an_engagement_to_another_organisation(
    isolated_dirs,
):
    """`POST /auth/projects` is the door that says which organisation owns an engagement.

    It was harmless for it to be `INSERT OR IGNORE` while almost nothing was registered. Now
    that creation registers everything, on-conflict-ignore would make it a permanent no-op -
    201 returned, nothing changed - on the one table that decides who reaches what. Asserted
    through both admins on a real door, not on the row: the row moving is only interesting
    because the access moves with it.
    """
    sysadmin = _client_for("move-sysadmin", "sysadmin")
    async with sysadmin:
        r = await sysadmin.post("/projects", json=_project_body("registry-moved"))
        assert r.status_code in (200, 201), r.text
        async with get_system_connection() as conn:
            home = await resolve_home_org_id(conn)
            acme = await insert_organisation(conn, slug="acme", name="Acme Ltd")
        r = await sysadmin.post(
            "/auth/projects",
            json={"slug": "registry-moved", "org_id": acme, "display_name": "Moved"},
        )
        assert r.status_code == 201, r.text

    acme_admin = _client_for("move-acme", "org_admin", org_id=acme)
    home_admin = _client_for("move-home", "org_admin", org_id=home)
    async with acme_admin, home_admin:
        r = await acme_admin.get("/projects/registry-moved/status")
        assert r.status_code == 200, f"the move did not reach the new owner: {r.text}"
        r = await home_admin.get("/projects/registry-moved/status")
        assert r.status_code == 403, f"the move did not leave the old owner: {r.text}"
        assert r.json()["detail"] == ACCESS_DENIED

        # And re-POSTing the project - which this endpoint answers 200 to - must not drag it
        # back. That is why creation uses register_project_if_unregistered and not the upsert.
        async with _client_for("move-sysadmin", "sysadmin") as sysadmin2:
            r = await sysadmin2.post("/projects", json=_project_body("registry-moved"))
            assert r.status_code in (200, 201), r.text
        r = await acme_admin.get("/projects/registry-moved/status")
        assert r.status_code == 200, f"re-creating the project moved it back: {r.text}"


@pytest.mark.asyncio
async def test_reassigning_a_project_without_a_name_keeps_the_one_it_has(isolated_dirs):
    """`POST /auth/projects` defaults `display_name` to `""`, and the upsert would overwrite.

    Moving an engagement between organisations is the door's purpose; blanking its curated name
    on the way past is not something anybody asked for, and `OrgDetail.tsx` renders the column
    straight, so the operator would simply see the slug appear.
    """
    sysadmin = _client_for("name-sysadmin", "sysadmin")
    async with sysadmin:
        r = await sysadmin.post("/projects", json=_project_body("registry-named"))
        assert r.status_code in (200, 201), r.text
        async with get_system_connection() as conn:
            acme = await insert_organisation(conn, slug="acme", name="Acme Ltd")
        r = await sysadmin.post(
            "/auth/projects",
            json={
                "slug": "registry-named",
                "org_id": acme,
                "display_name": "Grampian Sustainable Aviation",
            },
        )
        assert r.status_code == 201, r.text

        # Reassign again, this time saying nothing about the name.
        async with get_system_connection() as conn:
            home = await resolve_home_org_id(conn)
        r = await sysadmin.post(
            "/auth/projects", json={"slug": "registry-named", "org_id": home}
        )
        assert r.status_code == 201, r.text

    async with get_system_connection() as conn:
        row = await fetch_project_registry(conn, slug="registry-named")
    assert row["org_id"] == home, "the reassignment itself did not happen"
    assert row["display_name"] == "Grampian Sustainable Aviation"


@pytest.mark.asyncio
async def test_creation_fails_loudly_when_there_is_no_organisation_to_register_against(
    isolated_dirs, monkeypatch
):
    """A project nobody can reach must not be handed back as a 201.

    Silently skipping registration produces exactly the invisible state this branch exists to
    eliminate - and worse than the original, because the operator has just been told it worked.

    The state cannot be reached by deleting rows: every `get_system_connection` runs
    `init_system_db`, which re-seeds the home organisation before the handler's own query, so
    deleting it and then calling the endpoint simply finds it there again. `resolve_home_org_id`
    is therefore patched to its documented `None`, and what is under test is the endpoint's
    handling of that contract - the helper is annotated `int | None` and says in as many words
    that callers must treat None as "cannot register yet".

    Patched at `api.routers.projects`, where the name is looked up, not at `api.database`,
    where it is defined - the router binds its own reference with `from ... import`, and
    CLAUDE.md records four crew tests that patched the definition and silently tested nothing.
    """
    async def _no_home(conn):
        return None

    monkeypatch.setattr("api.routers.projects.resolve_home_org_id", _no_home)

    sysadmin = _client_for("loud-sysadmin", "sysadmin")
    async with sysadmin:
        r = await sysadmin.post("/projects", json=_project_body("registry-loud"))
    assert r.status_code == 500, f"an unregistrable project was created quietly: {r.text}"
    assert "could not be registered" in r.json()["detail"]
    assert "HOME_ORG_SLUG" in r.json()["detail"]


# ── Deleting an organisation ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_home_organisation_cannot_be_deleted(isolated_dirs):
    """It is what creation resolves against, and it can be empty of projects.

    So a rule that only counted registered projects would wave it straight through, and the
    next `POST /projects` would 500 with nothing to register against.
    """
    async with get_system_connection() as conn:
        home = await resolve_home_org_id(conn)

    sysadmin = _client_for("del-sysadmin", "sysadmin")
    async with sysadmin:
        r = await sysadmin.delete(f"/auth/orgs/{home}")
        assert r.status_code == 409, r.text
        assert "home organisation" in r.json()["detail"]
        assert "HOME_ORG_SLUG" in r.json()["detail"]

    async with get_system_connection() as conn:
        assert await resolve_home_org_id(conn) == home, "the home organisation went anyway"


@pytest.mark.asyncio
async def test_an_organisation_still_owning_projects_cannot_be_deleted(isolated_dirs):
    """The cascade would unregister every one of them in a single 204.

    A different failure from the one above and caught by a different condition: this
    organisation is not the home organisation, so the home rule says nothing about it. Asserted
    through a door as well as a row - the point of refusing is that the access survives.
    """
    sysadmin = _client_for("del2-sysadmin", "sysadmin")
    async with sysadmin:
        async with get_system_connection() as conn:
            acme = await insert_organisation(conn, slug="acme", name="Acme Ltd")
        r = await sysadmin.post("/projects", json=_project_body("registry-owned"))
        assert r.status_code in (200, 201), r.text
        r = await sysadmin.post(
            "/auth/projects", json={"slug": "registry-owned", "org_id": acme}
        )
        assert r.status_code == 201, r.text

        r = await sysadmin.delete(f"/auth/orgs/{acme}")
        assert r.status_code == 409, r.text
        assert "registry-owned" in r.json()["detail"], "the refusal did not name what is in the way"

    admin = _client_for("del2-admin", "org_admin", org_id=acme)
    async with admin:
        r = await admin.get("/projects/registry-owned/status")
        assert r.status_code == 200, f"the refused delete cascaded anyway: {r.text}"


@pytest.mark.asyncio
async def test_an_empty_non_home_organisation_can_still_be_deleted(isolated_dirs):
    """The guard is two conditions, not a blanket refusal - the door still works."""
    async with get_system_connection() as conn:
        spare = await insert_organisation(conn, slug="spare", name="Spare Ltd")

    sysadmin = _client_for("del3-sysadmin", "sysadmin")
    async with sysadmin:
        r = await sysadmin.delete(f"/auth/orgs/{spare}")
        assert r.status_code == 204, r.text

    async with get_system_connection() as conn:
        assert await fetch_organisation_by_slug(conn, slug="spare") is None


# ── The backfill ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def unregistered_estate(isolated_dirs):
    """Two real projects with their registry rows removed - the live deployment's state."""
    sysadmin = _client_for("backfill-sysadmin", "sysadmin")
    async with sysadmin:
        for slug in ("backfill-one", "backfill-two"):
            r = await sysadmin.post("/projects", json=_project_body(slug))
            assert r.status_code in (200, 201), r.text
    async with get_system_connection() as conn:
        await delete_project_registry(conn, slug="backfill-one")
        await delete_project_registry(conn, slug="backfill-two")
    return isolated_dirs / "data"


@pytest.mark.asyncio
async def test_backfill_dry_run_reports_without_writing(unregistered_estate):
    report = backfill_project_registry()
    assert report["applied"] is False
    assert sorted(report["registered"]) == ["backfill-one", "backfill-two"]
    async with get_system_connection() as conn:
        assert await fetch_project_registry(conn, slug="backfill-one") is None


@pytest.mark.asyncio
async def test_backfill_makes_the_estate_reachable_and_is_idempotent(unregistered_estate):
    first = backfill_project_registry(apply=True)
    assert sorted(first["registered"]) == ["backfill-one", "backfill-two"]
    assert first["already_registered"] == []

    async with get_system_connection() as conn:
        home = await resolve_home_org_id(conn)
    admin = _client_for("backfill-admin", "org_admin", org_id=home)
    async with admin:
        for slug in ("backfill-one", "backfill-two"):
            r = await admin.get(f"/projects/{slug}/status")
            assert r.status_code == 200, f"{slug}: {r.text}"

    second = backfill_project_registry(apply=True)
    assert second["registered"] == [], "the second run wrote rows again"
    assert sorted(second["already_registered"]) == ["backfill-one", "backfill-two"]

    # And the estate is still reachable - a second run must not have moved anything either.
    admin = _client_for("backfill-admin", "org_admin", org_id=home)
    async with admin:
        r = await admin.get("/projects/backfill-one/status")
        assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_backfill_refuses_an_organisation_it_cannot_find(unregistered_estate):
    """It must never create the organisation - a typo would otherwise make a second one."""
    with pytest.raises(BackfillRefused) as exc:
        backfill_project_registry(org_slug="no-such-org", apply=True)
    assert "does not create one" in str(exc.value)

    async with get_system_connection() as conn:
        assert await fetch_organisation_by_slug(conn, slug="no-such-org") is None
        assert await fetch_project_registry(conn, slug="backfill-one") is None


@pytest.mark.asyncio
async def test_backfill_skips_a_backup_copy_and_a_shell(unregistered_estate):
    """A `.db` file is not a project. Only a `projects` row naming the filename's slug is.

    The dated backup copies `reset_interview_artefacts.py` leaves behind carry a `projects` row
    for the *original* slug, and a probe-materialised database carries no `projects` row at all.
    Registering either would put a slug in the registry that no engagement answers to.
    """
    shutil.copy2(
        unregistered_estate / "backfill-one.db",
        unregistered_estate / "backfill-one.pre-interview-reset-2026-08-04.db",
    )
    sqlite3.connect(unregistered_estate / "probe-shell.db").close()

    # The third shape, and the one that actually occurs on the live deployment: a full schema
    # with an empty `projects` table. `vc-sort-check.db` is exactly this - `list_all_projects`
    # drops it too - and it is why the operator runbook expects three registrations from four
    # `.db` files. Without this case the report's own count could go on being wrong.
    empty = unregistered_estate / "vc-sort-check.db"
    shutil.copy2(unregistered_estate / "backfill-one.db", empty)
    with sqlite3.connect(empty) as c:
        c.execute("DELETE FROM projects")
        c.commit()

    report = backfill_project_registry(apply=True)
    assert sorted(report["registered"]) == ["backfill-one", "backfill-two"]
    reasons = {s["file"]: s["reason"] for s in report["skipped"]}
    assert "backfill-one.pre-interview-reset-2026-08-04.db" in reasons
    assert "backup" in reasons["backfill-one.pre-interview-reset-2026-08-04.db"]
    assert "no projects table" in reasons["probe-shell.db"]
    # Told apart from the shell above, not lumped in with it: one is a database that never had
    # the schema, the other has all of it and no project. Only the operator reading the report
    # can tell whether either is a surprise, and they cannot if both say the same thing.
    assert "projects table is empty" in reasons["vc-sort-check.db"]

    async with get_system_connection() as conn:
        assert await fetch_project_registry(conn, slug="probe-shell") is None
        assert await fetch_project_registry(conn, slug="vc-sort-check") is None
