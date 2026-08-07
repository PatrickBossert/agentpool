"""Integration tests for each tool. Requires ChromaDB running and ANTHROPIC_API_KEY set."""
import json
import pytest
from pathlib import Path
from api.config import get_settings



@pytest.mark.integration
def test_sqlite_state_tool_round_trip(test_slug, project_id):
    """A declared key, written by the agent that owns it.

    This used to write key='test_state' as agent 'test_agent'. Neither is declared, so
    check_write refused every write - and the assertion `"test_state" in write_result`
    passed anyway, because the refusal text quotes the key it is refusing. The write half
    of a round-trip test could not fail; only the read caught it.

    Asserting the success prefix rather than a substring is the point: a refusal names the
    key, the owner and the caller, so almost any substring drawn from the call itself will
    appear in the message that says the call was rejected.
    """
    from agents.tools.sqlite_state import SQLiteStateTool

    tool = SQLiteStateTool(slug=test_slug)

    write_result = tool._run(
        operation="write",
        key="value_chain_summary",
        agent_name="value_chain_mapper",
        value=json.dumps({"hello": "world"}),
    )
    assert write_result.startswith("Written to"), write_result

    read_result = tool._run(
        operation="read",
        key="value_chain_summary",
        agent_name="value_chain_mapper",
    )
    data = json.loads(read_result)
    assert data == {"hello": "world"}

    # Resolve through the ledger, not the disk. insert_agent_output_sync renames the write
    # to a _vN suffix, and latest_output_path - which this test used to call - returns the
    # highest number on disk rather than the current version. CLAUDE.md records four
    # incidents caused by that distinction.
    from agents.tools._db import current_output_path
    stored = current_output_path(test_slug, "value_chain_summary")
    assert stored is not None and stored.exists()
    assert json.loads(stored.read_text()) == {"hello": "world"}


@pytest.mark.integration
def test_human_input_tool_auto_respond(test_slug, project_id):
    """HumanInputTool with test_auto_respond inserts a review and returns immediately."""
    import sqlite3
    from pathlib import Path
    from agents.tools.human_input import HumanInputTool
    from api.config import get_settings

    settings = get_settings()

    # Create a crew_run record for the test
    db_path = Path(settings.database_dir) / f"{test_slug}.db"
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO crew_runs (project_id, crew_name, status) VALUES (?,?,?)",
        (project_id, "test", "running"),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()

    tool = HumanInputTool(slug=test_slug, run_id=run_id, test_auto_respond="approved")
    result = tool._run(prompt="Please review this output. Reply 'approved' to continue.")

    assert result == "approved"

    # Verify the human_reviews record was created
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "SELECT decision, prompt, crew_run_id FROM human_reviews WHERE crew_run_id=?",
        (run_id,),
    )
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "approved"
    assert "Please review" in row[1]
    assert row[2] == run_id


@pytest.mark.integration
def test_document_ingestion_tool(test_slug, chroma_client):
    from agents.tools.document_ingestion import DocumentIngestionTool

    tool = DocumentIngestionTool(slug=test_slug)

    result = tool._run(filename=None)  # ingest all docs in projects/{slug}/docs/
    assert "test_document.txt" in result

    # Verify documents are in ChromaDB (chroma_client uses Cloud or local as configured)
    collection = chroma_client.get_collection(f"{test_slug}_docs")
    count = collection.count()
    assert count > 0


@pytest.mark.integration
def test_chroma_query_tool(test_slug):
    """Requires documents already ingested by test_document_ingestion_tool."""
    from agents.tools.chroma_query import ChromaQueryTool

    tool = ChromaQueryTool(slug=test_slug, sector="logistics")

    result = tool._run(
        query="supply chain digital transformation priorities",
        collection="project",
        top_k=3,
    )

    assert isinstance(result, str)
    assert len(result) > 0
    # The fixture document mentions logistics — at least one chunk should match
    assert any(word in result.lower() for word in ["logistics", "supply", "digital", "transformation"])


@pytest.mark.integration
def test_tavily_search_tool():
    import os
    if not os.getenv("TAVILY_API_KEY"):
        pytest.skip("TAVILY_API_KEY not set")

    from agents.tools.tavily_search import TavilySearchTool

    tool = TavilySearchTool()
    result = tool._run(query="logistics industry digital transformation trends 2025", max_results=3)

    assert isinstance(result, str)
    assert len(result) > 50


@pytest.mark.integration
def test_mermaid_render_tool(test_slug):
    from agents.tools.mermaid_render import MermaidRenderTool
    from api.config import get_settings

    settings = get_settings()
    tool = MermaidRenderTool(slug=test_slug)

    mermaid_md = """```mermaid
graph LR
    A[Inbound Logistics] --> B[Operations]
    B --> C[Outbound Logistics]
    C --> D[Marketing & Sales]
    D --> E[Service]
```"""

    result = tool._run(mermaid_md=mermaid_md, filename="test_value_chain")

    assert "test_value_chain.md" in result
    # insert_agent_output_sync renames written outputs to a _vN suffix, so the
    # file lands as test_value_chain_v1.md rather than test_value_chain.md.
    outputs_dir = Path(settings.projects_dir) / test_slug / "outputs"
    written = sorted(outputs_dir.glob("test_value_chain*.md"))
    assert written, f"no test_value_chain markdown written to {outputs_dir}"
    assert "graph LR" in written[-1].read_text()
