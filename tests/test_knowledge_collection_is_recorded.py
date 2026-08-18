# tests/test_knowledge_collection_is_recorded.py
"""The store a document's chunks are in is a fact, not a calculation.

`client_documents.knowledge_tier` made the *tier* durable so a later operation could not
re-decide it. But the tier is only one of three inputs to a collection name. The other two -
the project's `sector` and the organisation its slug is registered to - were read fresh on
every delete and every reingest, and **both move through ordinary, correctly-gated doors**:
`sector` is deliberately not in `_PLATFORM_TIER_SETTINGS`, so a project_admin may change it
through `PATCH /{slug}/settings`, and `insert_project_registry` is documented as an upsert
that reassigns an engagement to another organisation.

So a delete could purge a store the write never used, answer **204**, and remove the row and
the file - leaving the text permanently retrievable in a shared store with nothing left that
could name it, because the row was the handle. In the organisation case the orphaned chunks
sit in a *different client's* store. That is Task 2's `documents.py:127` defect - "deletes
nothing and says nothing" - reintroduced through a different route: the door was made to fail
closed, but the address was still being recomputed rather than remembered.

The reingest door has the same root cause and a worse symptom: it *writes*, so a stale
address puts a second copy of the chunks in the wrong store rather than merely failing to
remove one from the right one.

This codebase already states the principle for a different resource - "Resolving an output:
ask the ledger, never the disk", where `agent_outputs.is_current` is authoritative precisely
because a filename-ordering scheme cannot express a revert. Same shape here: **an address
that is re-derived is an address that can move underneath the thing it points at.**

Every assertion below is on the collection Chroma was actually asked for, and each names the
store the document was *written* to rather than the one re-derivation would name today - a
test asserting the latter would pass against the defect.
"""
import io
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from api.config import get_settings
from api.database import fetch_document, get_connection, get_system_connection

SLUG = "collection-recorded"
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
    """This project's database and files, gone before and after every test - CLAUDE.md's
    poisoned-database trap, since DATABASE_DIR persists between runs."""
    import shutil

    def _wipe():
        settings = get_settings()
        (Path(settings.database_dir) / f"{SLUG}.db").unlink(missing_ok=True)
        shutil.rmtree(Path(settings.projects_dir) / SLUG, ignore_errors=True)
        # The registry row as well, and it is not tidiness. `project_registry` lives in the
        # shared system database, which no fixture here recreates, and `POST /projects`
        # registers through `register_project_if_unregistered` - an INSERT OR IGNORE. So a
        # test that reassigns this slug to another organisation leaves it there, and the
        # next test's freshly created project silently belongs to `rival-co`: the poisoned
        # database CLAUDE.md describes, in the half of it that no `.db` unlink reaches.
        system = Path(settings.database_dir) / "system.db"
        if system.exists():
            con = sqlite3.connect(str(system))
            con.execute("DELETE FROM project_registry WHERE slug=?", (SLUG,))
            con.execute("DELETE FROM organisations WHERE slug='rival-co'")
            con.commit()
            con.close()

    _wipe()
    yield
    get_settings.cache_clear()
    _wipe()


@pytest.fixture
def chroma():
    """Where the ingest writes - patched where ingest_service looks the factory up."""
    collection = MagicMock()
    mocked = MagicMock()
    mocked.get_or_create_collection.return_value = collection
    with patch("api.services.ingest_service.get_chroma_client", return_value=mocked):
        yield mocked


@pytest.fixture
def delete_chroma():
    """Where the delete purges - a different lookup, inside the handler, off
    `api.services.chroma_client`."""
    collection = MagicMock()
    mocked = MagicMock()
    mocked.get_or_create_collection.return_value = collection
    with patch("api.services.chroma_client.get_chroma_client", return_value=mocked):
        yield mocked


def _written(mocked) -> list[str]:
    return [
        call.args[0] if call.args else call.kwargs["name"]
        for call in mocked.get_or_create_collection.call_args_list
    ]


@pytest_asyncio.fixture
async def project(client):
    await client.post("/projects", json=PROJECT)
    return SLUG


async def _upload(client, *, tier, name="report.txt") -> int:
    resp = await client.post(
        f"/projects/{SLUG}/documents/upload",
        files={"file": (name, io.BytesIO(b"depot capacity notes"), "text/plain")},
        data={"tier": tier},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _recorded_collection(doc_id: int) -> str:
    async with get_connection(SLUG) as conn:
        doc = await fetch_document(conn, doc_id=doc_id)
    return doc["knowledge_collection"]


async def _move_the_sector(client, sector: str) -> None:
    """Change the project's sector through the door that owns it.

    `PATCH /{slug}/settings` round-trips the whole body, so the settings are read back and
    resent with one field changed - which is exactly what the Settings tab does. Driven
    through the real door rather than written into `projects.sector` by hand, because the
    finding is that an *ordinary, correctly-gated* change moves the address.
    """
    current = (await client.get(f"/projects/{SLUG}/settings")).json()
    resp = await client.patch(f"/projects/{SLUG}/settings", json={**current, "sector": sector})
    assert resp.status_code == 200, resp.text


async def _move_the_organisation(client, org_slug: str) -> None:
    """Reassign this engagement to another organisation through `POST /auth/projects`.

    An upsert by design - the door exists so an operator can say which organisation owns an
    engagement - and sysadmin-only, so this is a legitimate act by the one role permitted it.
    """
    async with get_system_connection() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO organisations (slug, name) VALUES (?,?)",
            (org_slug, org_slug.title()),
        )
        await conn.commit()
        cur = await conn.execute("SELECT id FROM organisations WHERE slug=?", (org_slug,))
        org_id = (await cur.fetchone())[0]
    resp = await client.post(
        "/auth/projects", json={"slug": SLUG, "org_id": org_id, "display_name": SLUG}
    )
    assert resp.status_code == 201, resp.text


# ── The address is recorded at the moment the chunks land ────────────────────────────────


@pytest.mark.asyncio
async def test_an_ingest_records_the_store_it_actually_wrote_into(client, chroma, project):
    """All three tiers, each recorded as the name Chroma was handed - not as the tier, and
    not as anything a later call would have to work out again."""
    for tier, expected in (
        ("project", f"{SLUG}_docs"),
        ("organisation", f"org_{get_settings().home_org_slug}"),
        ("sector", "sector_transport"),
    ):
        doc_id = await _upload(client, tier=tier, name=f"{tier}.txt")
        assert await _recorded_collection(doc_id) == expected, tier
    assert _written(chroma) == [
        f"{SLUG}_docs",
        f"org_{get_settings().home_org_slug}",
        "sector_transport",
    ]


# ── The two repros: the address moves underneath the document ────────────────────────────


@pytest.mark.asyncio
async def test_a_delete_purges_the_sector_store_the_write_used_not_todays(
    client, chroma, delete_chroma, project
):
    """Upload into `sector_transport`, move the project to `water`, delete.

    Before this fix the purge named `sector_water` - a store the write had never touched -
    answered 204, and removed the row and the file, so the chunks stayed retrievable in
    `sector_transport` with nothing left that could name them.
    """
    doc_id = await _upload(client, tier="sector")
    assert _written(chroma) == ["sector_transport"]

    await _move_the_sector(client, "water")

    resp = await client.delete(f"/projects/{SLUG}/documents/{doc_id}")
    assert resp.status_code == 204
    delete_chroma.get_or_create_collection.assert_called_once_with(name="sector_transport")
    assert "sector_water" not in _written(delete_chroma)


@pytest.mark.asyncio
async def test_a_delete_purges_the_organisation_store_the_write_used_not_todays(
    client, chroma, delete_chroma, project
):
    """The worse of the two, because the orphan crosses a client boundary.

    After an engagement is reassigned, re-derivation names the *new* organisation's store -
    so the delete both fails to remove the chunks it meant to and calls
    `get_or_create_collection` on a store belonging to somebody else, creating it if it did
    not exist.
    """
    home = f"org_{get_settings().home_org_slug}"
    doc_id = await _upload(client, tier="organisation")
    assert _written(chroma) == [home]

    await _move_the_organisation(client, "rival-co")

    resp = await client.delete(f"/projects/{SLUG}/documents/{doc_id}")
    assert resp.status_code == 204
    delete_chroma.get_or_create_collection.assert_called_once_with(name=home)
    assert "org_rival-co" not in _written(delete_chroma)


@pytest.mark.asyncio
async def test_a_reingest_rewrites_the_store_the_write_used_not_todays(
    client, chroma, project
):
    """A reingest *writes*, so a stale address is not a failure to remove - it is a second
    copy of the text in a store nobody asked to put it in, while the first copy stays."""
    doc_id = await _upload(client, tier="sector")
    await _move_the_sector(client, "water")

    resp = await client.post(f"/projects/{SLUG}/documents/{doc_id}/reingest")
    assert resp.status_code == 202
    assert _written(chroma) == ["sector_transport", "sector_transport"]
    assert "sector_water" not in _written(chroma)


@pytest.mark.asyncio
async def test_the_project_tier_is_unmoved_by_a_sector_change(
    client, chroma, delete_chroma, project
):
    """The control, and it is not decoration: `{slug}_docs` never depended on the sector, so
    a fix that simply stopped honouring settings changes would pass the two tests above and
    say nothing. This one fails if the recorded address is wrong for the common case."""
    doc_id = await _upload(client, tier="project")
    await _move_the_sector(client, "water")

    resp = await client.delete(f"/projects/{SLUG}/documents/{doc_id}")
    assert resp.status_code == 204
    delete_chroma.get_or_create_collection.assert_called_once_with(name=f"{SLUG}_docs")


@pytest.mark.asyncio
async def test_a_row_with_no_recorded_store_still_deletes(
    client, chroma, delete_chroma, project
):
    """The fallback, for a row written before the column existed and never re-ingested.

    Re-derivation is the old behaviour and is the best that can be done for an address that
    was never recorded - but it must still happen, or the fix would turn every legacy
    document into an undeletable one.
    """
    doc_id = await _upload(client, tier="project")
    async with get_connection(SLUG) as conn:
        await conn.execute(
            "UPDATE client_documents SET knowledge_collection='' WHERE id=?", (doc_id,)
        )
        await conn.commit()

    resp = await client.delete(f"/projects/{SLUG}/documents/{doc_id}")
    assert resp.status_code == 204
    delete_chroma.get_or_create_collection.assert_called_once_with(name=f"{SLUG}_docs")


# ── The migration, and what its backfill can and cannot promise ──────────────────────────


@pytest.mark.asyncio
async def test_a_database_at_the_previous_version_gains_the_collection_column(
    tmp_path, monkeypatch
):
    """Fails on _SCHEMA_VERSION 12 and passes on 13.

    A migration added without the bump silently never runs on any database already opened at
    the current version - no error, no warning, just rows that stay unmigrated for ever.
    """
    import api.database as db

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    slug = "legacy-collection-db"

    async with db.get_connection(slug):
        pass
    con = sqlite3.connect(str(tmp_path / f"{slug}.db"))
    con.execute("ALTER TABLE client_documents DROP COLUMN knowledge_collection")
    con.execute("PRAGMA user_version = 12")
    con.commit()
    con.close()
    db._MIGRATED.discard(slug)

    async with db.get_connection(slug) as conn:
        async with conn.execute("PRAGMA table_info(client_documents)") as cur:
            cols = {row["name"] async for row in cur}
    assert "knowledge_collection" in cols
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_backfill_is_exact_at_the_project_tier(tmp_path, monkeypatch):
    """`{slug}_docs` is recoverable with certainty: the slug is the database's own identity
    and cannot move, and until this branch there was no other store to be in."""
    import api.database as db

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    slug = "backfill-project-tier"

    async with db.get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "transport"),
        )
        await conn.execute(
            "INSERT INTO client_documents (project_id, filename, original_name, file_path,"
            " ingested, knowledge_tier, knowledge_collection)"
            " VALUES (1,'a.txt','a.txt','/tmp/a.txt',1,"
            "'project','')"
        )
        await conn.commit()
    con = sqlite3.connect(str(tmp_path / f"{slug}.db"))
    con.execute("PRAGMA user_version = 12")
    con.commit()
    con.close()
    db._MIGRATED.discard(slug)

    async with db.get_connection(slug) as conn:
        async with conn.execute(
            "SELECT knowledge_collection FROM client_documents WHERE id=1"
        ) as cur:
            assert (await cur.fetchone())[0] == f"{slug}_docs"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_backfill_freezes_the_sector_tier_at_todays_answer(tmp_path, monkeypatch):
    """And that is a freeze, not a recovery.

    A sector-tier row's true address is whatever the sector was when it was written, and
    nothing records that - so the backfill can only write what re-derivation would have
    said. What it buys is that the answer stops moving from here: the window in which the
    address can drift is closed at the migration rather than left open for ever.
    """
    import api.database as db

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    slug = "backfill-sector-tier"

    async with db.get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "transport"),
        )
        await conn.execute(
            "INSERT INTO client_documents (project_id, filename, original_name, file_path,"
            " ingested, knowledge_tier, knowledge_collection)"
            " VALUES (1,'a.txt','a.txt','/tmp/a.txt',1,"
            "'sector','')"
        )
        await conn.commit()
    con = sqlite3.connect(str(tmp_path / f"{slug}.db"))
    con.execute("PRAGMA user_version = 12")
    con.commit()
    con.close()
    db._MIGRATED.discard(slug)

    async with db.get_connection(slug) as conn:
        async with conn.execute(
            "SELECT knowledge_collection FROM client_documents WHERE id=1"
        ) as cur:
            assert (await cur.fetchone())[0] == "sector_transport"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_backfill_refuses_to_invent_a_store_for_a_project_with_no_sector(
    tmp_path, monkeypatch
):
    """`sector_` is the fallback defect in a second costume - a store silently shared by
    every project that names no sector. A row it cannot address honestly is left blank, and
    the delete door's fallback then raises rather than purging the wrong place."""
    import api.database as db

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    slug = "backfill-no-sector"

    async with db.get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, ""),
        )
        await conn.execute(
            "INSERT INTO client_documents (project_id, filename, original_name, file_path,"
            " ingested, knowledge_tier, knowledge_collection)"
            " VALUES (1,'a.txt','a.txt','/tmp/a.txt',1,"
            "'sector','')"
        )
        await conn.commit()
    con = sqlite3.connect(str(tmp_path / f"{slug}.db"))
    con.execute("PRAGMA user_version = 12")
    con.commit()
    con.close()
    db._MIGRATED.discard(slug)

    async with db.get_connection(slug) as conn:
        async with conn.execute(
            "SELECT knowledge_collection FROM client_documents WHERE id=1"
        ) as cur:
            assert (await cur.fetchone())[0] == ""
    get_settings.cache_clear()
