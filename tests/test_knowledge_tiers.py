# tests/test_knowledge_tiers.py
"""The knowledge tiers are named, and the sector store is nobody's fallback.

`ChromaQueryTool` resolved its collection argument with `.get(collection, f"sector_{sector}")`,
so the store shared by every engagement in a sector answered any name the dict did not hold.
A typo put one client's query into another client's material, and the graph recorded it as a
deliberate sector read.

Each tier is asserted on its own. A shared resolver makes it very easy for one tier's test to
be the only thing standing behind another's - so `project` is not allowed to stand in for
`interviews`, nor `sector` for `organisation` - and each is asserted twice over: once on
`collection_for`, and once on a caller, because a resolver that is right and unused is a
property held one layer away from where it matters.
"""
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from api.services.knowledge_tiers import (
    KNOWLEDGE_TIERS,
    collection_for,
    org_slug_for_project,
)


# ── The refusal: the defect this task closes ─────────────────────────────────────────────

def test_an_unrecognised_tier_is_refused_not_answered_from_the_sector_store():
    with pytest.raises(ValueError):
        collection_for("sectr", slug="acme", sector="energy", org_slug="sp")


def test_the_refusal_names_the_tiers_rather_than_the_store_it_declined_to_read():
    with pytest.raises(ValueError) as excinfo:
        collection_for("sectr", slug="acme", sector="energy", org_slug="sp")
    message = str(excinfo.value)
    assert "sector_energy" not in message
    for tier in KNOWLEDGE_TIERS:
        assert tier in message


def test_an_empty_tier_is_refused_too():
    """The shape a caller passing through an unset argument arrives in."""
    with pytest.raises(ValueError):
        collection_for("", slug="acme", sector="energy", org_slug="sp")


# ── Each tier, separately ────────────────────────────────────────────────────────────────

def test_the_project_tier_resolves_to_this_projects_own_document_store():
    assert collection_for(
        "project", slug="acme", sector="energy", org_slug="sp"
    ) == "acme_docs"


def test_the_interviews_tier_resolves_to_this_projects_interview_store():
    assert collection_for(
        "interviews", slug="acme", sector="energy", org_slug="sp"
    ) == "acme_interviews"


def test_the_sector_tier_resolves_to_the_shared_sector_store():
    assert collection_for(
        "sector", slug="acme", sector="energy", org_slug="sp"
    ) == "sector_energy"


def test_the_organisation_tier_resolves_to_this_organisations_store():
    assert collection_for(
        "organisation", slug="acme", sector="energy", org_slug="sp"
    ) == "org_sp"


def test_the_four_tiers_resolve_to_four_different_stores():
    """A resolver that answered two tiers with one name would pass each test above."""
    names = {
        tier: collection_for(tier, slug="acme", sector="energy", org_slug="sp")
        for tier in KNOWLEDGE_TIERS
    }
    assert len(set(names.values())) == len(KNOWLEDGE_TIERS)


# ── A tier whose key is absent is refused, never widened ─────────────────────────────────

def test_the_organisation_tier_is_refused_when_the_project_has_no_registry_row():
    """No `project_registry` row means the project belongs to no organisation, which is a
    real state - every project lacked one before sp39 - and the answer is a refusal, the
    same one `check_project_access` gives on its org branch. Not the sector store, and not
    `org_` with nothing after it."""
    with pytest.raises(ValueError):
        collection_for("organisation", slug="acme", sector="energy", org_slug=None)


def test_the_sector_tier_is_refused_when_the_project_names_no_sector():
    """`sector_` is a valid collection name and would be shared by every project that names
    no sector, which is the fallback defect in a second costume."""
    with pytest.raises(ValueError):
        collection_for("sector", slug="acme", sector="", org_slug="sp")


def test_the_project_tier_is_refused_without_a_slug():
    with pytest.raises(ValueError):
        collection_for("project", slug="", sector="energy", org_slug="sp")


# ── org_slug comes from project_registry ─────────────────────────────────────────────────

@pytest.fixture
def system_db(tmp_path, monkeypatch):
    """A system database holding one organisation and one registered project."""
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    con = sqlite3.connect(str(tmp_path / "system.db"))
    con.execute("CREATE TABLE organisations (id INTEGER PRIMARY KEY, slug TEXT, name TEXT)")
    con.execute("CREATE TABLE project_registry (id INTEGER PRIMARY KEY, slug TEXT, "
                "org_id INTEGER, display_name TEXT)")
    con.execute("INSERT INTO organisations (id, slug, name) VALUES (1, 'scottish-power', "
                "'Scottish Power')")
    con.execute("INSERT INTO project_registry (id, slug, org_id) VALUES (1, 'property', 1)")
    con.commit()
    con.close()
    yield tmp_path
    get_settings.cache_clear()


def test_a_registered_project_resolves_its_organisations_slug(system_db):
    assert org_slug_for_project("property") == "scottish-power"


def test_an_unregistered_project_resolves_no_organisation(system_db):
    assert org_slug_for_project("acme") is None


def test_the_organisation_store_is_shared_by_two_projects_of_one_organisation(system_db):
    """The tier's reason for existing: two projects, one store. Asserted end to end, because
    `org_slug_for_project` returning the right slug and `collection_for` naming the right
    store are separately true and only jointly useful."""
    con = sqlite3.connect(str(system_db / "system.db"))
    con.execute("INSERT INTO project_registry (id, slug, org_id) VALUES (2, 'generation', 1)")
    con.commit()
    con.close()

    def store(slug):
        return collection_for(
            "organisation", slug=slug, org_slug=org_slug_for_project(slug)
        )

    assert store("property") == store("generation") == "org_scottish-power"


# ── The caller: ChromaQueryTool ──────────────────────────────────────────────────────────

@pytest.fixture
def project(tmp_path, monkeypatch):
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    yield tmp_path
    get_settings.cache_clear()


def _chroma_client():
    col = MagicMock()
    col.count.return_value = 3
    col.query.return_value = {"documents": [["a chunk"]], "metadatas": [[{}]]}
    client = MagicMock()
    client.get_collection.return_value = col
    return client


def _run_tool(collection, *, slug="acme", sector="energy"):
    """Run ChromaQueryTool against a mocked Chroma and return (output, client)."""
    from agents.tools.chroma_query import ChromaQueryTool

    client = _chroma_client()
    tool = ChromaQueryTool(slug=slug, sector=sector)
    with patch("agents.tools.chroma_query.get_chroma_client", return_value=client), \
         patch("agents.tools.chroma_query._chroma_reachable", return_value=True):
        out = tool._run(query="how do we operate?", collection=collection)
    return out, client


def test_the_tool_reads_the_sector_store_when_the_agent_asks_for_it(project):
    _, client = _run_tool("sector")
    client.get_collection.assert_called_once_with("sector_energy")


def test_the_tool_reads_the_project_store_for_the_project_tier(project):
    _, client = _run_tool("project")
    client.get_collection.assert_called_once_with("acme_docs")


def test_the_tool_reads_the_interview_store_for_the_interviews_tier(project):
    _, client = _run_tool("interviews")
    client.get_collection.assert_called_once_with("acme_interviews")


def test_the_tool_reads_the_organisation_store_for_the_organisation_tier(project):
    con = sqlite3.connect(str(project / "system.db"))
    con.execute("CREATE TABLE organisations (id INTEGER PRIMARY KEY, slug TEXT, name TEXT)")
    con.execute("CREATE TABLE project_registry (id INTEGER PRIMARY KEY, slug TEXT, "
                "org_id INTEGER)")
    con.execute("INSERT INTO organisations (id, slug, name) VALUES (1, 'scottish-power', 'SP')")
    con.execute("INSERT INTO project_registry (id, slug, org_id) VALUES (1, 'acme', 1)")
    con.commit()
    con.close()

    _, client = _run_tool("organisation")
    client.get_collection.assert_called_once_with("org_scottish-power")


def test_the_tool_refuses_a_tier_it_does_not_know_and_reads_nothing(project):
    """The defect, at the layer it actually bit: an agent naming 'sectr' used to be handed
    the shared sector store's contents."""
    out, client = _run_tool("sectr")
    client.get_collection.assert_not_called()
    assert "sector_energy" not in out
    assert "sectr" in out


def test_the_tool_refuses_the_organisation_tier_for_an_unregistered_project(project):
    """No registry row, no organisation tier - and emphatically not the sector store."""
    out, client = _run_tool("organisation")
    client.get_collection.assert_not_called()
    assert "sector_energy" not in out


def test_the_tools_schema_accepts_the_four_tiers_and_nothing_else():
    """A refusal inside `_run` is unreachable if the schema rejects the value first, and a
    tier missing from the Literal is a tier no agent can ever name."""
    from pydantic import ValidationError

    from agents.tools.chroma_query import ChromaQueryToolInput

    for tier in KNOWLEDGE_TIERS:
        assert ChromaQueryToolInput(query="x", collection=tier).collection == tier
    with pytest.raises(ValidationError):
        ChromaQueryToolInput(query="x", collection="sectr")


# ── The caller: chat retrieval ───────────────────────────────────────────────────────────

def test_chat_retrieval_reads_the_project_tier():
    """Agent chat searches the project's own documents and nothing wider. Asserted on the
    name it asks Chroma for, because that is the only thing that decides whose material
    comes back."""
    client = _chroma_client()
    with patch("api.services.chat_retrieval_service.get_chroma_client", return_value=client):
        from api.services.chat_retrieval_service import search
        search("acme", "what is the process?")

    client.get_collection.assert_called_once_with("acme_docs")
