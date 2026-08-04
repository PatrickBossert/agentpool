# tests/test_chroma_citations.py
"""A retrieved chunk that cannot say where it came from cannot be cited.

ChromaQueryTool returned `results["documents"]` and discarded `metadatas`, so Morgan's
required `source` field was impossible to satisfy - she could only infer a document name from
the prose or invent one - and Casey's instruction to cite `answer_id` referred to a value the
tool threw away.

The stored filename is a hash (d89a0be7c73442a08cde5080b0797c16.pdf). Offering that as the
citation would be technically a source and useless to a person, so the tests below assert on
the original name and the doc_id that resolves to it.
"""
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from agents.tools.chroma_query import ChromaQueryTool, ChromaQueryToolInput

HASHED = "d89a0be7c73442a08cde5080b0797c16.pdf"
ORIGINAL = "SPUK_2025_Annual_Accounts.pdf"


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project database holding one document, so doc_id can resolve to a real name."""
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))

    con = sqlite3.connect(str(tmp_path / "acme.db"))
    con.execute("CREATE TABLE client_documents (id INTEGER PRIMARY KEY, filename TEXT, "
                "original_name TEXT)")
    con.execute("INSERT INTO client_documents (id, filename, original_name) VALUES (?,?,?)",
                (3, HASHED, ORIGINAL))
    con.commit()
    con.close()
    yield
    get_settings.cache_clear()


def _tool_returning(metadatas, documents):
    col = MagicMock()
    col.count.return_value = 10
    col.query.return_value = {"documents": [documents], "metadatas": [metadatas]}
    client = MagicMock()
    client.get_collection.return_value = col
    return client


def test_the_interviews_collection_is_an_accepted_value():
    """It was added to the description and the collection mapping and not to the Literal, so
    a call naming it was rejected by schema validation before it ever ran."""
    parsed = ChromaQueryToolInput(query="x", collection="interviews")
    assert parsed.collection == "interviews"


def test_a_project_result_names_the_document_a_person_could_open(project):
    tool = ChromaQueryTool(slug="acme", sector="utilities")
    client = _tool_returning(
        [{"filename": HASHED, "chunk": 12, "doc_id": 3}],
        ["Asset condition data is recorded inconsistently."],
    )
    with patch("agents.tools.chroma_query.get_chroma_client", return_value=client), \
         patch("agents.tools.chroma_query._chroma_reachable", return_value=True):
        out = tool._run(query="asset condition", collection="project")

    assert ORIGINAL in out
    assert "doc_id=3" in out
    # The hash is a source and not a citation - a reader cannot open it or recognise it.
    assert HASHED not in out


def test_the_chunk_text_is_still_returned(project):
    """The citation is an addition. Replacing the text with a header would make the tool
    useless in a way every other assertion here would happily pass."""
    tool = ChromaQueryTool(slug="acme", sector="utilities")
    client = _tool_returning(
        [{"filename": HASHED, "chunk": 12, "doc_id": 3}],
        ["Asset condition data is recorded inconsistently."],
    )
    with patch("agents.tools.chroma_query.get_chroma_client", return_value=client), \
         patch("agents.tools.chroma_query._chroma_reachable", return_value=True):
        out = tool._run(query="asset condition", collection="project")

    assert "Asset condition data is recorded inconsistently." in out


def test_an_interview_result_carries_the_answer_id(project):
    """What Casey was told to cite and could not."""
    tool = ChromaQueryTool(slug="acme", sector="utilities")
    client = _tool_returning(
        [{"answer_id": 812, "node_id": "1.2", "discipline": "data",
          "relationship": "internal", "elicitation": "unprompted"}],
        ["For compliance, yes. For investment, no."],
    )
    with patch("agents.tools.chroma_query.get_chroma_client", return_value=client), \
         patch("agents.tools.chroma_query._chroma_reachable", return_value=True):
        out = tool._run(query="asset record", collection="interviews")

    assert "answer_id=812" in out
    # The tags Casey weights evidence by. Without them he is back to reading prose.
    assert "unprompted" in out
    assert "data" in out


def test_a_doc_id_with_no_matching_document_still_renders(project):
    """A dangling doc_id must not take the whole retrieval down with it - the text is still
    worth having, and the missing name is itself the finding."""
    tool = ChromaQueryTool(slug="acme", sector="utilities")
    client = _tool_returning(
        [{"filename": HASHED, "chunk": 1, "doc_id": 999}],
        ["Some retrieved text."],
    )
    with patch("agents.tools.chroma_query.get_chroma_client", return_value=client), \
         patch("agents.tools.chroma_query._chroma_reachable", return_value=True):
        out = tool._run(query="x", collection="project")

    assert "Some retrieved text." in out
    assert "999" in out


def test_results_with_no_metadata_still_return_their_text(project):
    """The sector collection is shared and was ingested without doc ids. Requiring metadata
    would silently empty a knowledge base several agents depend on."""
    tool = ChromaQueryTool(slug="acme", sector="utilities")
    client = _tool_returning([None], ["Sector benchmark text."])
    with patch("agents.tools.chroma_query.get_chroma_client", return_value=client), \
         patch("agents.tools.chroma_query._chroma_reachable", return_value=True):
        out = tool._run(query="x", collection="sector")

    assert "Sector benchmark text." in out


def test_each_result_is_attributed_separately(project):
    """Two chunks from different documents must not share one citation - an agent citing the
    first name it sees would attribute half its evidence to the wrong source."""
    tool = ChromaQueryTool(slug="acme", sector="utilities")
    client = _tool_returning(
        [{"doc_id": 3, "chunk": 1}, {"doc_id": 999, "chunk": 4}],
        ["First chunk.", "Second chunk."],
    )
    with patch("agents.tools.chroma_query.get_chroma_client", return_value=client), \
         patch("agents.tools.chroma_query._chroma_reachable", return_value=True):
        out = tool._run(query="x", collection="project")

    assert out.index("doc_id=3") < out.index("First chunk.")
    assert out.index("doc_id=999") < out.index("Second chunk.")
    assert out.index("First chunk.") < out.index("doc_id=999")
