# tests/test_knowledge_tier_ingestion.py
"""Material only ever moves narrower.

A project's documents never land in its organisation's store; an organisation's never land
in its sector's. Without that rule one division's investment proposals become another
division's search results, and nobody would think to look for the reason.

Every assertion here is on **the collection Chroma was actually asked for**, because that is
the only thing that decides whose material a later retrieval returns. A test that checked
which tier a router had parsed, or that a resolver returns the right string, would be the
failure mode CLAUDE.md records: a property verified one layer away from where it holds.

Each tier and each door is asserted separately. The two upload doors share a resolver and a
rule, which is exactly the arrangement that lets one path's test silently cover another's -
so the documents door is never allowed to stand in for the chat door, nor the project tier
for the organisation tier.
"""
import io
import json
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.auth import create_access_token
from api.config import get_settings
from api.services.ingest_service import (
    IngestError,
    chunk_filter_for,
    ingest_collection,
    ingest_document,
)
from api.services.knowledge_tiers import (
    TierWriteRefused,
    assert_may_write_tier,
    writable_tiers,
)

SLUG = "tier-ingest"
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
    from pathlib import Path

    def _wipe():
        settings = get_settings()
        (Path(settings.database_dir) / f"{SLUG}.db").unlink(missing_ok=True)
        shutil.rmtree(Path(settings.projects_dir) / SLUG, ignore_errors=True)

    _wipe()
    yield
    get_settings.cache_clear()
    _wipe()


SYSADMIN = {"sub": "admin", "role": "sysadmin"}
ORG_ADMIN = {"sub": "connie", "role": "org_admin", "org_id": 1}
REVIEWER = {"sub": "raj", "role": "reviewer"}


# ── The rule: who may write how wide ─────────────────────────────────────────────────────

def test_a_reviewer_may_write_the_project_tier_and_nothing_wider():
    assert writable_tiers(REVIEWER) == ("project",)


def test_an_org_admin_may_write_their_organisation_but_not_the_sector():
    assert writable_tiers(ORG_ADMIN) == ("organisation", "project")


def test_the_sector_store_is_sysadmin_alone():
    """On a consultancy deployment the sector store spans different clients."""
    assert "sector" in writable_tiers(SYSADMIN)
    assert "sector" not in writable_tiers(ORG_ADMIN)
    assert "sector" not in writable_tiers(REVIEWER)


def test_a_caller_with_no_token_at_all_may_write_nothing_wider_than_project():
    assert writable_tiers(None) == ("project",)


def test_an_approver_is_refused_the_organisation_tier():
    with pytest.raises(TierWriteRefused):
        assert_may_write_tier("organisation", REVIEWER)


def test_an_org_admin_is_refused_the_sector_tier():
    with pytest.raises(TierWriteRefused):
        assert_may_write_tier("sector", ORG_ADMIN)


def test_a_sysadmin_may_write_every_uploadable_tier():
    for tier in ("project", "organisation", "sector"):
        assert_may_write_tier(tier, SYSADMIN)


def test_the_interview_store_is_not_an_upload_tier_for_anybody():
    """It holds what somebody actually said. A document filed there would be retrieved with
    an answer's provenance - and the refusal is 'no such upload tier', not 'not yours', so
    even a sysadmin cannot reach it."""
    with pytest.raises(ValueError) as excinfo:
        assert_may_write_tier("interviews", SYSADMIN)
    assert not isinstance(excinfo.value, TierWriteRefused)


def test_an_unknown_tier_is_a_different_refusal_from_an_unauthorised_one():
    """Folding them together tells somebody who made a typo that they lack authority."""
    with pytest.raises(ValueError) as excinfo:
        assert_may_write_tier("organization", SYSADMIN)
    assert not isinstance(excinfo.value, TierWriteRefused)


# ── The resolver an ingestion writes through ─────────────────────────────────────────────

@pytest.fixture
def registered(tmp_path, monkeypatch):
    """DATABASE_DIR holding a system database that registers `tier-ingest` to an org."""
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    con = sqlite3.connect(str(tmp_path / "system.db"))
    con.execute("CREATE TABLE organisations (id INTEGER PRIMARY KEY, slug TEXT, name TEXT)")
    con.execute("CREATE TABLE project_registry (id INTEGER PRIMARY KEY, slug TEXT, "
                "org_id INTEGER)")
    con.execute("INSERT INTO organisations (id, slug, name) VALUES (1, 'scottish-power', 'SP')")
    con.execute(f"INSERT INTO project_registry (id, slug, org_id) VALUES (1, '{SLUG}', 1)")
    con.commit()
    con.close()
    yield tmp_path
    get_settings.cache_clear()


def test_a_project_ingestion_writes_this_projects_own_store(registered):
    assert ingest_collection(SLUG, "project") == f"{SLUG}_docs"


def test_an_organisation_ingestion_writes_the_organisations_store(registered):
    assert ingest_collection(SLUG, "organisation") == "org_scottish-power"


def test_a_sector_ingestion_writes_the_sector_store(registered):
    assert ingest_collection(SLUG, "sector", sector="transport") == "sector_transport"


def test_a_project_ingestion_is_unmoved_by_a_sector_or_an_organisation(registered):
    """The one-way rule, at the resolver: the project branch passes neither key to
    `collection_for`, so there is nothing for a sector or an organisation to resolve to
    however the call is decorated."""
    assert ingest_collection(SLUG, "project", sector="transport") == f"{SLUG}_docs"


def test_a_collection_name_is_not_a_tier(registered):
    """The lever an ingestion offers is a closed vocabulary of three, never a store name."""
    with pytest.raises(ValueError):
        ingest_collection(SLUG, "sector_transport")


def test_an_ingestion_into_the_interview_store_is_refused(registered):
    with pytest.raises(ValueError):
        ingest_collection(SLUG, "interviews")


def test_the_organisation_tier_is_refused_for_an_unregistered_project(tmp_path, monkeypatch):
    """No registry row, no organisation store - and emphatically not the sector's."""
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        ingest_collection(SLUG, "organisation")
    get_settings.cache_clear()


def test_the_chunk_filter_is_project_scoped_only_where_the_collection_is_not():
    """`doc_id` is a per-project SQLite id and the broader stores are shared, so two projects
    will each hold a document 7. At the project tier the collection is already the scope, and
    every chunk ingested before this branch carries no slug to filter on."""
    assert chunk_filter_for("a", 7, "project") == {"doc_id": 7}
    assert chunk_filter_for("a", 7, "organisation") == {
        "$and": [{"doc_id": 7}, {"slug": "a"}]
    }


# ── ingest_document: where the bytes actually go ─────────────────────────────────────────

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


@pytest_asyncio.fixture
async def doc(client, tmp_path):
    """A project created through the API, plus a text file on disk to ingest."""
    await client.post("/projects", json=PROJECT)
    path = tmp_path / "notes.txt"
    path.write_text("the depot runs two shifts")
    return str(path)


@pytest.mark.asyncio
async def test_an_ingestion_that_declares_nothing_writes_the_project_store(doc, chroma):
    """The default is the narrowest. A default of anything broader would make the safe case
    the one requiring thought."""
    await ingest_document(SLUG, 1, doc)
    assert _written_collections(chroma) == [f"{SLUG}_docs"]


@pytest.mark.asyncio
async def test_an_organisation_ingestion_writes_the_organisation_store_and_not_the_projects(
    doc, chroma
):
    await ingest_document(SLUG, 1, doc, tier="organisation")
    written = _written_collections(chroma)
    assert written == ["org_future-edge"]
    assert f"{SLUG}_docs" not in written


@pytest.mark.asyncio
async def test_a_sector_ingestion_writes_the_projects_own_sector_store(doc, chroma):
    """The sector is read off the project, never taken from the caller - a caller-supplied
    sector would let one engagement write into another sector's shared store."""
    await ingest_document(SLUG, 1, doc, tier="sector")
    assert _written_collections(chroma) == ["sector_transport"]


@pytest.mark.asyncio
async def test_an_ingestion_at_an_unknown_tier_reaches_no_store_at_all(doc, chroma):
    with pytest.raises(IngestError):
        await ingest_document(SLUG, 1, doc, tier="sector_transport", raise_on_error=True)
    chroma.get_or_create_collection.assert_not_called()


@pytest.mark.asyncio
async def test_an_ingestion_into_the_interview_store_reaches_no_store_at_all(doc, chroma):
    with pytest.raises(IngestError):
        await ingest_document(SLUG, 1, doc, tier="interviews", raise_on_error=True)
    chroma.get_or_create_collection.assert_not_called()


@pytest.mark.asyncio
async def test_a_shared_store_chunk_carries_the_slug_that_wrote_it(doc, chroma):
    """Otherwise a later delete filtering on doc_id alone takes another project's document."""
    await ingest_document(SLUG, 7, doc, tier="organisation")
    upsert = chroma.get_or_create_collection.return_value.upsert
    metadatas = upsert.call_args.kwargs["metadatas"]
    assert all(m["slug"] == SLUG for m in metadatas)


# ── The documents door ───────────────────────────────────────────────────────────────────

async def _upload(client, chroma, *, tier=None, name="report.txt"):
    data = {"tier": tier} if tier is not None else None
    return await client.post(
        f"/projects/{SLUG}/documents/upload",
        files={"file": (name, io.BytesIO(b"depot capacity notes"), "text/plain")},
        data=data,
    )


@pytest.mark.asyncio
async def test_the_documents_door_defaults_to_the_project_store(client, chroma):
    await client.post("/projects", json=PROJECT)
    resp = await _upload(client, chroma)
    assert resp.status_code == 201
    assert resp.json()["knowledge_tier"] == "project"
    assert _written_collections(chroma) == [f"{SLUG}_docs"]


@pytest.mark.asyncio
async def test_the_documents_door_writes_the_organisation_store_when_asked_by_a_sysadmin(
    client, chroma
):
    await client.post("/projects", json=PROJECT)
    resp = await _upload(client, chroma, tier="organisation")
    assert resp.status_code == 201
    assert _written_collections(chroma) == ["org_future-edge"]


@pytest.mark.asyncio
async def test_the_documents_door_writes_the_sector_store_when_asked_by_a_sysadmin(
    client, chroma
):
    await client.post("/projects", json=PROJECT)
    resp = await _upload(client, chroma, tier="sector")
    assert resp.status_code == 201
    assert _written_collections(chroma) == ["sector_transport"]


@pytest.mark.asyncio
async def test_the_documents_door_refuses_a_tier_it_does_not_know_and_files_nothing(
    client, chroma
):
    await client.post("/projects", json=PROJECT)
    resp = await _upload(client, chroma, tier="organization")
    assert resp.status_code == 422
    chroma.get_or_create_collection.assert_not_called()
    listing = await client.get(f"/projects/{SLUG}/documents")
    assert listing.json() == []


@pytest.mark.asyncio
async def test_the_documents_door_refuses_the_interview_store(client, chroma):
    await client.post("/projects", json=PROJECT)
    resp = await _upload(client, chroma, tier="interviews")
    assert resp.status_code == 422
    chroma.get_or_create_collection.assert_not_called()


async def _org_admin_client() -> AsyncClient:
    """An org_admin of the home organisation - the one POST /projects registers to, so
    `check_project_access` lets them through to the tier question."""
    from api.database import get_system_connection
    from api.main import app

    async with get_system_connection() as conn:
        cur = await conn.execute(
            "SELECT id FROM organisations WHERE slug=?", (get_settings().home_org_slug,)
        )
        org_id = (await cur.fetchone())[0]
    token = create_access_token("connie", "org_admin", "test-secret", org_id=org_id)
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.mark.asyncio
async def test_an_org_admin_is_refused_the_sector_store_at_the_documents_door(client, chroma):
    """The door opens for an org_admin - it is `require_org_admin_or_above` - and the tier is
    still refused, because the two are separate questions and only the second is about how
    far the material travels."""
    await client.post("/projects", json=PROJECT)
    async with await _org_admin_client() as admin:
        resp = await admin.post(
            f"/projects/{SLUG}/documents/upload",
            files={"file": ("x.txt", io.BytesIO(b"text"), "text/plain")},
            data={"tier": "sector"},
        )
    assert resp.status_code == 403
    assert "sector" in resp.json()["detail"]
    chroma.get_or_create_collection.assert_not_called()
    listing = await client.get(f"/projects/{SLUG}/documents")
    assert listing.json() == []


@pytest.mark.asyncio
async def test_an_org_admin_may_write_their_own_organisations_store(client, chroma):
    """The other half of the same door, so the refusal above is not merely 'org_admins are
    refused everything wider than project'."""
    await client.post("/projects", json=PROJECT)
    async with await _org_admin_client() as admin:
        resp = await admin.post(
            f"/projects/{SLUG}/documents/upload",
            files={"file": ("x.txt", io.BytesIO(b"annual report"), "text/plain")},
            data={"tier": "organisation"},
        )
    assert resp.status_code == 201
    assert _written_collections(chroma) == ["org_future-edge"]


# ── The chat door: authority, and the auto-enable ────────────────────────────────────────

@pytest.fixture
def chat_approver():
    """The chat door's own gate held open - this section is about the tier, not the gate.

    Not a weakening: tests/test_write_door_authority.py drives the gate over HTTP as a real
    member. Patched on the router module, where the name is looked up.
    """
    with patch("api.routers.agent_chat.caller_may_approve", new=AsyncMock(return_value=True)):
        yield


async def _chat_upload(client, *, tier=None, name="notes.txt"):
    data = {"agent_name": "Interview Coordinator"}
    if tier is not None:
        data["tier"] = tier
    return await client.post(
        f"/projects/{SLUG}/agent-chat/upload",
        data=data,
        files={"file": (name, b"the depot runs two shifts", "text/plain")},
    )


async def _discovery_ids(slug: str) -> list[int]:
    from api.database import fetch_project, get_connection

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
    return json.loads(project.get("config_json") or "{}").get("discovery_document_ids", [])


@pytest.mark.asyncio
async def test_an_organisation_chat_upload_lands_in_the_organisation_store_and_is_not_enabled(
    client, chroma, chat_approver
):
    """The headline of this task's step 5, and both halves matter.

    `discovery_document_ids` is one project's list of inputs. Auto-enabling a chat upload
    there is a convenience at the project tier - the file was uploaded here and is readable
    here alone. At the organisation tier it is shared material with unshared enablement:
    a document every project of the organisation can read, silently added to *this* one's
    discovery inputs, which nobody would think to look for.
    """
    await client.post("/projects", json=PROJECT)
    resp = await _chat_upload(client, tier="organisation")
    assert resp.status_code == 201
    assert resp.json()["knowledge_tier"] == "organisation"
    assert _written_collections(chroma) == ["org_future-edge"]
    assert await _discovery_ids(SLUG) == []


@pytest.mark.asyncio
async def test_a_project_chat_upload_is_still_auto_enabled_into_discovery(
    client, chroma, chat_approver
):
    """The convenience is right at the project tier and must survive - a conditional that
    disabled it everywhere would pass the test above and break the feature."""
    await client.post("/projects", json=PROJECT)
    resp = await _chat_upload(client)
    assert resp.status_code == 201
    assert _written_collections(chroma) == [f"{SLUG}_docs"]
    assert await _discovery_ids(SLUG) == [resp.json()["doc_id"]]


@pytest.mark.asyncio
async def test_a_sector_chat_upload_is_not_enabled_into_discovery_either(
    client, chroma, chat_approver
):
    """Asserted for itself rather than left to the organisation tier's test: one tier's
    coverage standing in for another's is how this project has been bitten twice."""
    await client.post("/projects", json=PROJECT)
    resp = await _chat_upload(client, tier="sector")
    assert resp.status_code == 201
    assert _written_collections(chroma) == ["sector_transport"]
    assert await _discovery_ids(SLUG) == []


@pytest.mark.asyncio
async def test_an_approver_may_not_promote_material_through_the_chat_door(
    client, chroma, chat_approver
):
    """The chat door's gate is the `approver` content role, the documents door's is
    org_admin. The asymmetry stands; what must not stand is a caller reaching a wider store
    because they came through the weaker door."""
    from api.main import app

    token = create_access_token("raj", "reviewer", "test-secret")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as approver:
        await client.post("/projects", json=PROJECT)
        with patch("api.routers.agent_chat.check_project_access", new=AsyncMock()):
            resp = await approver.post(
                f"/projects/{SLUG}/agent-chat/upload",
                data={"agent_name": "Interview Coordinator", "tier": "organisation"},
                files={"file": ("notes.txt", b"text", "text/plain")},
            )
    assert resp.status_code == 403
    assert "organisation" in resp.json()["detail"]
    chroma.get_or_create_collection.assert_not_called()
    listing = await client.get(f"/projects/{SLUG}/documents")
    assert listing.json() == []


# ── The delete door: it deletes, or it says so ───────────────────────────────────────────

@pytest.fixture
def delete_chroma():
    """Mocked Chroma patched where the delete door looks it up - inside the handler, off
    `api.services.chroma_client`, which is a different lookup from the ingest path's."""
    collection = MagicMock()
    client = MagicMock()
    client.get_or_create_collection.return_value = collection
    with patch("api.services.chroma_client.get_chroma_client", return_value=client):
        yield client


async def _upload_and_ingest(client, chroma, *, tier=None):
    resp = await _upload(client, chroma, tier=tier)
    doc_id = resp.json()["id"]
    from api.database import get_connection, update_document_ingested

    async with get_connection(SLUG) as conn:
        await update_document_ingested(conn, doc_id=doc_id)
    return doc_id


@pytest.mark.asyncio
async def test_deleting_a_project_document_purges_the_project_store(
    client, chroma, delete_chroma
):
    await client.post("/projects", json=PROJECT)
    doc_id = await _upload_and_ingest(client, chroma)
    resp = await client.delete(f"/projects/{SLUG}/documents/{doc_id}")
    assert resp.status_code == 204
    delete_chroma.get_or_create_collection.assert_called_once_with(name=f"{SLUG}_docs")
    delete_chroma.get_or_create_collection.return_value.delete.assert_called_once_with(
        where={"doc_id": doc_id}
    )


@pytest.mark.asyncio
async def test_deleting_an_organisation_document_purges_the_organisation_store(
    client, chroma, delete_chroma
):
    """The tier comes off the row. Resolving it any other way is how a delete comes to
    address a store the write never used - which deletes nothing and says nothing."""
    await client.post("/projects", json=PROJECT)
    doc_id = await _upload_and_ingest(client, chroma, tier="organisation")
    resp = await client.delete(f"/projects/{SLUG}/documents/{doc_id}")
    assert resp.status_code == 204
    delete_chroma.get_or_create_collection.assert_called_once_with(name="org_future-edge")
    delete_chroma.get_or_create_collection.return_value.delete.assert_called_once_with(
        where={"$and": [{"doc_id": doc_id}, {"slug": SLUG}]}
    )


@pytest.mark.asyncio
async def test_a_delete_that_cannot_reach_chroma_refuses_and_keeps_the_document(
    client, chroma, delete_chroma
):
    """This block was `except Exception: pass`. A wrong collection name deleted nothing and
    said nothing, leaving every chunk retrievable after the operator believed the document
    gone - and the row and the file were gone, so there was nothing left to retry with.

    The chunks now go first and the failure is the caller's: the document survives, which is
    what makes a retry possible at all."""
    await client.post("/projects", json=PROJECT)
    doc_id = await _upload_and_ingest(client, chroma)
    delete_chroma.get_or_create_collection.return_value.delete.side_effect = RuntimeError(
        "chroma down"
    )

    resp = await client.delete(f"/projects/{SLUG}/documents/{doc_id}")
    assert resp.status_code == 502
    assert "not been deleted" in resp.json()["detail"].lower()

    listing = await client.get(f"/projects/{SLUG}/documents")
    assert doc_id in [d["id"] for d in listing.json()]


@pytest.mark.asyncio
async def test_a_document_that_was_never_ingested_deletes_without_touching_chroma(
    client, chroma, delete_chroma
):
    await client.post("/projects", json=PROJECT)
    with patch("api.routers.documents.ingest_document", new_callable=AsyncMock):
        resp = await _upload(client, chroma)
    doc_id = resp.json()["id"]
    assert (await client.delete(f"/projects/{SLUG}/documents/{doc_id}")).status_code == 204
    delete_chroma.get_or_create_collection.assert_not_called()


# ── Reingest keeps the tier the write declared ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_reingest_returns_the_document_to_the_store_it_was_filed_in(client, chroma):
    """A retry must not re-decide the tier: a default here would quietly move an
    organisation document into the project store, breaking the one-way rule with a button
    labelled 'retry'."""
    await client.post("/projects", json=PROJECT)
    upload = await _upload(client, chroma, tier="organisation")
    doc_id = upload.json()["id"]
    chroma.get_or_create_collection.reset_mock()

    resp = await client.post(f"/projects/{SLUG}/documents/{doc_id}/reingest")
    assert resp.status_code == 202
    assert _written_collections(chroma) == ["org_future-edge"]


# ── The column reaches a database that already exists ────────────────────────────────────

@pytest.mark.asyncio
async def test_a_database_at_the_previous_version_gains_the_knowledge_tier_column(
    tmp_path, monkeypatch
):
    """Fails on _SCHEMA_VERSION 11 and passes on 12. A migration added without the bump
    silently never runs on any database that has already been opened once."""
    import api.database as db

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    slug = "legacy-tier-db"

    async with db.get_connection(slug):
        pass
    con = sqlite3.connect(str(tmp_path / f"{slug}.db"))
    con.execute("ALTER TABLE client_documents DROP COLUMN knowledge_tier")
    con.execute("PRAGMA user_version = 11")
    con.commit()
    con.close()
    db._MIGRATED.discard(slug)

    async with db.get_connection(slug) as conn:
        async with conn.execute("PRAGMA table_info(client_documents)") as cur:
            cols = {row["name"] async for row in cur}
    assert "knowledge_tier" in cols
    get_settings.cache_clear()
