"""Integration tests for each tool. Requires ChromaDB running and ANTHROPIC_API_KEY set."""
import json
import pytest
from pathlib import Path
from api.config import get_settings



@pytest.mark.integration
def test_sqlite_state_tool_round_trip(test_slug, project_id):
    from agents.tools.sqlite_state import SQLiteStateTool
    settings = get_settings()

    tool = SQLiteStateTool(slug=test_slug)

    # Write a value
    write_result = tool._run(
        operation="write",
        key="test_state",
        agent_name="test_agent",
        value=json.dumps({"hello": "world"}),
    )
    assert "test_state" in write_result

    # Read it back
    read_result = tool._run(
        operation="read",
        key="test_state",
        agent_name="test_agent",
    )
    data = json.loads(read_result)
    assert data == {"hello": "world"}

    # Verify file was written
    file_path = Path(settings.projects_dir) / test_slug / "outputs" / "test_state.json"
    assert file_path.exists()


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
def test_document_ingestion_tool(test_slug):
    from agents.tools.document_ingestion import DocumentIngestionTool
    from api.config import get_settings
    import chromadb

    settings = get_settings()
    tool = DocumentIngestionTool(slug=test_slug)

    result = tool._run(filename=None)  # ingest all docs in projects/{slug}/docs/
    assert "test_document.txt" in result

    # Verify documents are in ChromaDB
    client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    collection = client.get_collection(f"{test_slug}_docs")
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
    file_path = Path(settings.projects_dir) / test_slug / "outputs" / "test_value_chain.md"
    assert file_path.exists()
    assert "graph LR" in file_path.read_text()
