# tests/test_secure_mode_tiers.py
"""A sensitive project resolves **every** knowledge tier to the local Chroma.

This was already true when the file was written, and that is the whole reason it exists. It was
true by a property nobody had written down: `get_chroma_client(slug)` is chosen **per project**,
and the one client it returns serves whatever collection it is later asked for - so `sector_*`,
`org_*`, `{slug}_docs` and `{slug}_interviews` all inherit the project's mode without any of
them being considered separately. "Already true" and "asserted" are different things, and
CLAUDE.md states this one absolutely: a sensitive project's documents stay off Chroma Cloud.

Two changes would break it silently, and each has a guard here:

- **A client chosen per collection.** Plausible the moment somebody wants the sector store
  hosted while a client's own documents stay local. `test_the_chroma_client_is_chosen_per
  _project_and_not_per_collection` fails on the signature, and the four behavioural tests below
  fail on the client actually constructed for each tier.
- **A seventh caller building its own client.** Six callers pass a real slug today; a seventh
  reaching for `chromadb.CloudClient` from `CHROMA_API_KEY` would bypass the mode entirely,
  which is exactly what `DocumentIngestionTool` and the document delete each did once
  (`tests/test_secure_mode_document_paths.py` records both). The seam guard below reads the
  source rather than the call graph, so a caller in a file nobody thought to check still lands.

**Each tier is asserted on its own, in both directions.** A shared resolver is precisely what
lets one tier's test cover another's - the masking this project has documented twice - so every
tier is driven through a real caller that names *that* tier, and asserted on the collection the
client was asked for as well as on which client class was built. The standard-mode half is not
decoration: without it a test asserting "local" would pass just as well against an
implementation that had stopped building a cloud client at all.

`CHROMA_API_KEY` is set throughout, because that is the exact condition that forces
`CloudClient`.
"""
import ast
import inspect
import sqlite3
from pathlib import Path

import pytest

from api.config import get_settings
from api.services.knowledge_tiers import KNOWLEDGE_TIERS, UPLOADABLE_TIERS

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SEAM = "api/services/chroma_client.py"

# Tier -> the collection that tier resolves to for the fixtures below. Written out rather than
# computed from `collection_for`, deliberately: a test that built its expectation with the same
# resolver the code under test uses would agree with a resolver that answered every tier with
# one name. `tests/test_knowledge_tiers.py` asserts the resolver; this asserts the store each
# tier's material actually reached.
_SECURE_COLLECTIONS = {
    "project": "secure-tiers_docs",
    "interviews": "secure-tiers_interviews",
    "sector": "sector_rail",
    "organisation": "org_scottish-power",
}
_OPEN_COLLECTIONS = {
    "project": "open-tiers_docs",
    "interviews": "open-tiers_interviews",
    "sector": "sector_rail",
    "organisation": "org_scottish-power",
}


class _FakeCollection:
    def __init__(self, name):
        self.name = name
        self.upserts = []

    def count(self):
        return 1

    def query(self, **kw):
        return {"documents": [["a chunk of the client's material"]], "metadatas": [[{}]]}

    def upsert(self, **kw):
        self.upserts.append(kw)


class _FakeClient:
    def __init__(self, kind, record):
        self.kind = kind
        record.append(kind)
        record.clients[kind] = self
        self.asked_for = []

    def get_collection(self, name=None, **kw):
        self.asked_for.append(name)
        return _FakeCollection(name)

    def get_or_create_collection(self, name=None, **kw):
        self.asked_for.append(name)
        collection = _FakeCollection(name)
        self.collection = collection
        return collection


class _Built(list):
    def __init__(self):
        super().__init__()
        self.clients: dict[str, _FakeClient] = {}


@pytest.fixture
def built(monkeypatch):
    """Record which Chroma client class was constructed, and what it was asked for."""
    import chromadb
    record = _Built()
    monkeypatch.setattr(chromadb, "CloudClient", lambda **kw: _FakeClient("cloud", record))
    monkeypatch.setattr(chromadb, "HttpClient", lambda **kw: _FakeClient("local", record))
    return record


@pytest.fixture
def tiered_projects(tmp_path, monkeypatch):
    """One sensitive and one standard project, both in one organisation, in one process.

    Both, and in one process, because a per-deployment implementation passes every
    single-project test and fails only this shape. The system database gives both a
    `project_registry` row, without which the organisation tier is refused before any client is
    built and the organisation cases below would assert nothing.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("CHROMA_API_KEY", "cloud-key-is-set")
    get_settings.cache_clear()

    for slug, mode in (("secure-tiers", "sensitive"), ("open-tiers", "standard")):
        conn = sqlite3.connect(tmp_path / f"{slug}.db")
        conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, "
                     "llm_mode TEXT, sector TEXT, config_json TEXT)")
        conn.execute("INSERT INTO projects (slug, llm_mode, sector) VALUES (?,?,?)",
                     (slug, mode, "rail"))
        # `projects` and nothing else. `client_documents` is deliberately left to
        # `get_connection`'s own migrations: a hand-rolled copy of it was missing `ingested`,
        # which the sector-tier ingest reaches through `resolve_ingest_collection` and the
        # other two tiers do not - so the fixture was quietly deciding which tiers could be
        # tested.
        conn.commit()
        conn.close()

    system = sqlite3.connect(tmp_path / "system.db")
    system.execute("CREATE TABLE organisations (id INTEGER PRIMARY KEY, slug TEXT, name TEXT)")
    system.execute("CREATE TABLE project_registry (id INTEGER PRIMARY KEY, slug TEXT, "
                   "org_id INTEGER, display_name TEXT)")
    system.execute("INSERT INTO organisations (id, slug, name) VALUES "
                   "(1, 'scottish-power', 'Scottish Power')")
    system.executemany("INSERT INTO project_registry (slug, org_id) VALUES (?, 1)",
                       [("secure-tiers",), ("open-tiers",)])
    system.commit()
    system.close()

    from api.services import chroma_client
    chroma_client._MODE_CACHE.clear()
    yield tmp_path
    chroma_client._MODE_CACHE.clear()
    get_settings.cache_clear()


def _query(slug: str, tier: str) -> str:
    """The read path an agent actually takes to a tier: the tool, naming the tier."""
    from agents.tools.chroma_query import ChromaQueryTool
    return ChromaQueryTool(slug=slug, sector="rail")._run("what does the client do?", tier)


# ── Reading: every tier, both modes ───────────────────────────────────────────────────────


@pytest.mark.parametrize("tier", KNOWLEDGE_TIERS)
def test_a_sensitive_project_reads_every_tier_from_the_local_chroma(
    tiered_projects, built, tier, monkeypatch
):
    """The guarantee, tier by tier - including the two stores whose names carry no slug.

    `sector_` and `org_` are the collections a reader would most expect to be exempt, since
    neither is this project's alone. They are not exempt: the material travelling to them is
    still this project's query text, and what comes back is still material the agent will quote
    into its output.
    """
    monkeypatch.setattr("agents.tools.chroma_query._chroma_reachable", lambda *a, **k: True)
    result = _query("secure-tiers", tier)

    assert built == ["local"], (
        f"a sensitive project's {tier} tier reached Chroma Cloud"
    )
    assert built.clients["local"].asked_for == [_SECURE_COLLECTIONS[tier]], (
        "the local client was built but a different store was queried"
    )
    assert "Error" not in result and "not found" not in result, (
        f"the {tier} query did not actually reach a collection: {result!r}"
    )


@pytest.mark.parametrize("tier", KNOWLEDGE_TIERS)
def test_a_standard_project_reads_every_tier_from_chroma_cloud(
    tiered_projects, built, tier, monkeypatch
):
    """Guard the guard, per tier.

    If nothing could reach `CloudClient` any more - a hardwired local client, a broken tool, a
    fixture that stopped setting `CHROMA_API_KEY` - the test above would pass while asserting
    nothing at all. This says the mode genuinely moves *this* tier, which is what makes the
    sensitive answer a decision rather than a constant.
    """
    monkeypatch.setattr("agents.tools.chroma_query._chroma_reachable", lambda *a, **k: True)
    _query("open-tiers", tier)

    assert built == ["cloud"], f"a standard project's {tier} tier did not reach Chroma Cloud"
    assert built.clients["cloud"].asked_for == [_OPEN_COLLECTIONS[tier]]


def test_both_modes_are_honoured_for_every_tier_in_one_process(
    tiered_projects, built, monkeypatch
):
    """The test a deployment-wide switch cannot pass, run over all four tiers at once."""
    monkeypatch.setattr("agents.tools.chroma_query._chroma_reachable", lambda *a, **k: True)
    for tier in KNOWLEDGE_TIERS:
        _query("secure-tiers", tier)
        _query("open-tiers", tier)

    assert built == ["local", "cloud"] * len(KNOWLEDGE_TIERS)


# ── Writing: every tier a document can be uploaded at ─────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", UPLOADABLE_TIERS)
async def test_a_sensitive_project_writes_every_uploadable_tier_to_the_local_chroma(
    tiered_projects, built, tier
):
    """Reading a shared store and writing one are different risks, and the write is the larger.

    A query sends the agent's query text; an ingestion sends the full text of the client's own
    documents. The organisation and sector tiers only became writable on this branch, so this
    is the first change at which a sensitive project's documents could be sent to a store
    outside it at all.
    """
    from api.services.ingest_service import ingest_document

    doc = tiered_projects / "confidential.md"
    doc.write_text("Confidential board strategy.")
    await ingest_document("secure-tiers", 1, str(doc), tier=tier)

    assert built == ["local"], f"a sensitive project's {tier} ingest reached Chroma Cloud"
    client = built.clients["local"]
    assert client.asked_for == [_SECURE_COLLECTIONS[tier]]
    assert client.collection.upserts, "nothing was actually indexed"


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", UPLOADABLE_TIERS)
async def test_a_standard_project_writes_every_uploadable_tier_to_chroma_cloud(
    tiered_projects, built, tier
):
    """The other half of the branch, per tier - see the read-side guard above for why."""
    from api.services.ingest_service import ingest_document

    doc = tiered_projects / "ordinary.md"
    doc.write_text("An ordinary document.")
    await ingest_document("open-tiers", 1, str(doc), tier=tier)

    assert built == ["cloud"], f"a standard project's {tier} ingest stayed local"
    assert built.clients["cloud"].asked_for == [_OPEN_COLLECTIONS[tier]]


# ── The properties that make the four above hold, rather than happen to hold ───────────────


def test_this_file_covers_every_tier_the_vocabulary_declares():
    """A fifth tier must not arrive untested.

    The parametrised cases read `KNOWLEDGE_TIERS`, so a new tier joins them automatically - but
    only if somebody also adds the collection it resolves to. Without this, a tier missing from
    `_SECURE_COLLECTIONS` would raise a `KeyError` inside the test and read as a broken test
    rather than as an untested tier.
    """
    assert set(_SECURE_COLLECTIONS) == set(KNOWLEDGE_TIERS)
    assert set(_OPEN_COLLECTIONS) == set(KNOWLEDGE_TIERS)
    assert set(UPLOADABLE_TIERS) <= set(KNOWLEDGE_TIERS)
    assert len(set(_SECURE_COLLECTIONS.values())) == len(KNOWLEDGE_TIERS), (
        "two tiers resolve to one store, so one tier's test is standing in for another's"
    )


def test_the_chroma_client_is_chosen_per_project_and_not_per_collection():
    """The unwritten property the whole guarantee rests on, written down.

    Every tier is local for a sensitive project because the client is a function of the slug
    **alone**: one client, whatever collection it is later asked for. A `collection` or `tier`
    parameter here would make each tier a separate decision, and the first one somebody got
    wrong would be silent - a `CloudClient` built for a project that should never have had one
    raises nothing and warns nobody.

    If a per-collection client is genuinely wanted one day, this is the test to change, and
    changing it means re-pointing the four behavioural cases above at whatever new argument
    decides it - which is the conversation this assertion exists to force.
    """
    from api.services.chroma_client import get_chroma_client

    assert list(inspect.signature(get_chroma_client).parameters) == ["slug"], (
        "get_chroma_client no longer decides per project alone. Every knowledge tier is local "
        "for a sensitive project because one client serves them all; a per-collection client "
        "makes each tier its own decision, and a wrong one is silent."
    )


def _client_construction_sites() -> dict[str, list[str]]:
    """Every `chromadb.<something>Client(...)` call under `api/`, `agents/` and `scripts/`.

    Read from the source rather than by enumerating callers, because enumeration is what missed
    `DocumentIngestionTool` and the document delete: both were found by a person reading files,
    after the routing they bypassed had been tested and believed. A parse sees a file nobody
    thought to open.

    Matched on the attribute name ending in `Client`, not on a list of the two classes in use
    today: `EphemeralClient` and `PersistentClient` exist in the same namespace, and a guard
    naming only `HttpClient` and `CloudClient` would wave either through.
    """
    sites: dict[str, list[str]] = {}
    for pattern in ("api/**/*.py", "agents/**/*.py", "scripts/**/*.py"):
        for path in sorted(_REPO_ROOT.glob(pattern)):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                is_client_call = (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr.endswith("Client")
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "chromadb"
                )
                if is_client_call:
                    key = str(path.relative_to(_REPO_ROOT))
                    sites.setdefault(key, []).append(node.func.attr)
    return sites


def test_no_chroma_client_is_constructed_outside_the_seam():
    """The seventh caller, refused before it can exist.

    Six callers reach `get_chroma_client` today and every one passes a real slug. What the mode
    cannot survive is a caller that never asks - `chromadb.CloudClient(api_key=...)` built from
    the environment sends a sensitive project's material off the premises with no branch to
    read, no error, and nothing on the privacy page to notice.
    """
    sites = _client_construction_sites()
    assert set(sites) == {_SEAM}, (
        f"a Chroma client is constructed outside {_SEAM}: "
        f"{ {k: v for k, v in sites.items() if k != _SEAM} }. Deployment mode is decided per "
        "project in that one file; a client built anywhere else has no mode to obey."
    )
    assert sorted(sites[_SEAM]) == ["CloudClient", "HttpClient", "HttpClient"], (
        "the seam's own client construction changed - check that the sensitive branch still "
        f"returns a local client before anything else: {sites[_SEAM]}"
    )
