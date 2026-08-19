"""A sensitive project's documents stay off Chroma Cloud on every path that touches them.

tests/test_secure_mode_routing.py proves the factory routes per project. That is not the
same claim as this one: the factory only decides for the callers that ask it. Two paths were
still constructing `chromadb.CloudClient` from `CHROMA_API_KEY` alone, and each was found by
enumerating callers rather than by any test failing -

- `DocumentIngestionTool`, held by value_chain_mapper and requirements_analyst, which ingests
  the client's own corporate documents into `{slug}_docs`; and
- `DELETE /{slug}/documents/{doc_id}`, whose Chroma cleanup sits inside `except: pass`.

The delete case is worse than a leak on its own: upload now indexes locally for a sensitive
project, so a cloud-targeted delete removed nothing, silently, and the chunks stayed
retrievable after the operator deleted the document.

Every test here therefore sets CHROMA_API_KEY - the exact condition that used to force
CloudClient - and asserts on which client class was constructed, not on which helper was
called.
"""
import io
import sqlite3
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from api.config import get_settings


class _FakeCollection:
    def __init__(self):
        self.upserts = []
        self.deletes = []

    def upsert(self, **kw):
        self.upserts.append(kw)

    def delete(self, **kw):
        self.deletes.append(kw)


class _FakeClient:
    def __init__(self, kind, built):
        self.kind = kind
        self.collection = _FakeCollection()
        built.append(kind)

    def get_or_create_collection(self, name=None, **kw):
        self.collection.name = name
        return self.collection


class _Built(list):
    """The list of client kinds constructed, with the fakes themselves kept alongside."""

    def __init__(self):
        super().__init__()
        self.clients: dict[str, _FakeClient] = {}


@pytest.fixture
def built(monkeypatch):
    """Record which Chroma client class each path constructs."""
    import chromadb
    record = _Built()

    def _cloud(**kw):
        record.clients["cloud"] = _FakeClient("cloud", record)
        return record.clients["cloud"]

    def _local(**kw):
        record.clients["local"] = _FakeClient("local", record)
        return record.clients["local"]

    monkeypatch.setattr(chromadb, "CloudClient", _cloud)
    monkeypatch.setattr(chromadb, "HttpClient", _local)
    return record


def _seed_project(db_dir, slug, mode):
    conn = sqlite3.connect(db_dir / f"{slug}.db")
    conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, "
                 "llm_mode TEXT, sector TEXT, config_json TEXT)")
    conn.execute("INSERT INTO projects (slug, llm_mode, sector) VALUES (?,?,?)",
                 (slug, mode, "rail"))
    conn.commit()
    conn.close()


@pytest.fixture
def ingest_projects(tmp_path, monkeypatch):
    """One sensitive and one standard project, each with a document on disk to ingest."""
    db_dir = tmp_path / "data"
    proj_dir = tmp_path / "projects"
    db_dir.mkdir()
    monkeypatch.setenv("DATABASE_DIR", str(db_dir))
    monkeypatch.setenv("PROJECTS_DIR", str(proj_dir))
    monkeypatch.setenv("CHROMA_API_KEY", "cloud-key-is-set")
    get_settings.cache_clear()
    for slug, mode in (("secure-docs", "sensitive"), ("open-docs", "standard")):
        _seed_project(db_dir, slug, mode)
        docs = proj_dir / slug / "docs"
        docs.mkdir(parents=True)
        (docs / "corporate-strategy.md").write_text("Confidential internal strategy.")
    yield
    get_settings.cache_clear()


def test_alex_ingests_a_sensitive_project_into_the_local_chroma(ingest_projects, built):
    """DocumentIngestionTool built CloudClient from CHROMA_API_KEY with no mode check at all.

    Asserts the ingest actually landed as well as where the client pointed: a tool that
    returns an error string still "does not reach cloud", and would pass the negative half
    of this on its own.
    """
    from agents.tools.document_ingestion import DocumentIngestionTool

    result = DocumentIngestionTool(slug="secure-docs")._run()

    assert built == ["local"], "a sensitive project's documents must not reach Chroma Cloud"
    assert "corporate-strategy.md" in result
    assert built.clients["local"].collection.upserts, "nothing was actually indexed"


def test_alex_still_ingests_a_standard_project_into_the_cloud(ingest_projects, built):
    """The other side of the branch - routed per project, not hardwired local."""
    from agents.tools.document_ingestion import DocumentIngestionTool

    DocumentIngestionTool(slug="open-docs")._run()
    assert built == ["cloud"]


def test_the_two_modes_are_honoured_in_one_process(ingest_projects, built):
    """The test a deployment-wide switch cannot pass."""
    from agents.tools.document_ingestion import DocumentIngestionTool

    DocumentIngestionTool(slug="secure-docs")._run()
    DocumentIngestionTool(slug="open-docs")._run()
    assert built == ["local", "cloud"]


@pytest_asyncio.fixture
async def uploaded_document(tmp_path, monkeypatch, client):
    """A sensitive project with one document uploaded and marked ingested.

    Created through the API and the real schema, because the delete endpoint under test is
    driven over HTTP and reads a real documents row.
    """
    db_dir = tmp_path / "data"
    db_dir.mkdir()
    monkeypatch.setenv("DATABASE_DIR", str(db_dir))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("CHROMA_API_KEY", "cloud-key-is-set")
    get_settings.cache_clear()

    r = await client.post(
        "/projects",
        json={"client_slug": "secure-del", "llm_mode": "sensitive", "sector": "rail"},
    )
    assert r.status_code in (200, 201), r.text
    # The upload queues a real background ingest. Stubbed out so this fixture neither
    # reaches for a Chroma server nor records a client construction that belongs to setup
    # rather than to the delete under test; the row is marked ingested below instead.
    with patch("api.routers.documents.ingest_document", new_callable=AsyncMock):
        r = await client.post(
            "/projects/secure-del/documents/upload",
            files={"file": ("policy.md", io.BytesIO(b"Confidential policy."), "text/markdown")},
        )
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]

    from api.database import get_connection, update_document_ingested
    async with get_connection("secure-del") as conn:
        await update_document_ingested(conn, doc_id=doc_id)

    yield doc_id
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_deleting_a_sensitive_project_document_deletes_from_the_local_chroma(
    uploaded_document, built, client
):
    """Upload indexes locally; the delete used to target the cloud, inside `except: pass`.

    Nothing surfaced: the endpoint returned 204, the row went, the file went, and the chunks
    stayed in the local collection - still retrievable, permanently, with no way for the
    operator to tell.
    """
    r = await client.delete(f"/projects/secure-del/documents/{uploaded_document}")
    assert r.status_code == 204

    assert built == ["local"], "the delete went to the wrong Chroma"
    assert built.clients["local"].collection.deletes == [{"where": {"doc_id": uploaded_document}}]
