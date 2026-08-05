# tests/test_lineage_capture.py
"""What an output was built from, taken from what its run actually read."""
import pytest
import pytest_asyncio

from api.database import get_connection, insert_project
from api.services.lineage_service import fetch_lineage

SLUG = "lineage-test"


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch):
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="utilities", config_json="{}"
        )
    yield tmp_path
    get_settings.cache_clear()


async def _output(conn, agent, output_type, version, is_current=1):
    cur = await conn.execute(
        "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
        " version, is_current, review_status) VALUES (1,?,?,?,?,?,'pending')",
        (agent, output_type, f"{output_type}_v{version}.json", version, is_current),
    )
    await conn.commit()
    return cur.lastrowid


@pytest.mark.asyncio
async def test_an_output_links_to_every_input_its_run_read(project):
    from agents.tools._db import link_output_sync, record_run_input_sync

    async with get_connection(SLUG) as conn:
        model = await _output(conn, "value_chain_mapper", "value_chain_model", 8)
        levers = await _output(conn, "value_lever_analyst", "value_levers", 2)

    record_run_input_sync(SLUG, 20, model)
    record_run_input_sync(SLUG, 20, levers)

    async with get_connection(SLUG) as conn:
        scripts = await _output(conn, "interaction_designer", "interview_scripts", 5)
    link_output_sync(SLUG, 20, scripts)

    async with get_connection(SLUG) as conn:
        rows = {r["output_id"]: r for r in await fetch_lineage(conn, project_id=1)}
    assert sorted(rows[scripts]["input_output_ids"]) == sorted([model, levers])


@pytest.mark.asyncio
async def test_rows_carry_both_id_and_output_id(project):
    """Task 4's tests index by output_id; the staleness rule downstream indexes by id.
    Both must be present, and they must agree."""
    from agents.tools._db import link_output_sync

    async with get_connection(SLUG) as conn:
        levers = await _output(conn, "value_lever_analyst", "value_levers", 2)
    link_output_sync(SLUG, 24, levers)

    async with get_connection(SLUG) as conn:
        rows = await fetch_lineage(conn, project_id=1)
    row = next(r for r in rows if r["output_id"] == levers)
    assert row["id"] == row["output_id"] == levers


@pytest.mark.asyncio
async def test_reading_the_same_input_twice_makes_one_edge(project):
    from agents.tools._db import link_output_sync, record_run_input_sync

    async with get_connection(SLUG) as conn:
        model = await _output(conn, "value_chain_mapper", "value_chain_model", 8)
    record_run_input_sync(SLUG, 21, model)
    record_run_input_sync(SLUG, 21, model)

    async with get_connection(SLUG) as conn:
        scripts = await _output(conn, "interaction_designer", "interview_scripts", 6)
    link_output_sync(SLUG, 21, scripts)

    async with get_connection(SLUG) as conn:
        rows = {r["output_id"]: r for r in await fetch_lineage(conn, project_id=1)}
    assert rows[scripts]["input_output_ids"] == [model]


@pytest.mark.asyncio
async def test_an_output_that_read_nothing_has_no_ancestry(project):
    """Morgan works from documents. No state ancestry is the honest answer, and it must not
    read as an error or as freshness."""
    from agents.tools._db import link_output_sync

    async with get_connection(SLUG) as conn:
        levers = await _output(conn, "value_lever_analyst", "value_levers", 2)
    link_output_sync(SLUG, 22, levers)

    async with get_connection(SLUG) as conn:
        rows = {r["output_id"]: r for r in await fetch_lineage(conn, project_id=1)}
    assert rows[levers]["input_output_ids"] == []


@pytest.mark.asyncio
async def test_documents_retrieved_are_recorded_as_citations(project):
    from agents.tools._db import link_output_sync, record_run_document_sync

    async with get_connection(SLUG) as conn:
        await conn.execute(
            "INSERT INTO client_documents (id, project_id, filename, original_name,"
            " file_path, content_type, size_bytes) VALUES (3,1,'h.pdf','Annual.pdf','x','p',1)"
        )
        await conn.commit()
        levers = await _output(conn, "value_lever_analyst", "value_levers", 2)

    record_run_document_sync(SLUG, 22, 3)
    link_output_sync(SLUG, 22, levers)

    async with get_connection(SLUG) as conn:
        rows = {r["output_id"]: r for r in await fetch_lineage(conn, project_id=1)}
    assert rows[levers]["document_ids"] == [3]


@pytest.mark.asyncio
async def test_a_later_read_does_not_attach_to_an_earlier_write(project):
    """Links are taken at write time. Attaching everything a run ever read to everything it
    ever wrote would claim an output was built from something written after it.

    An unrelated run (99) reads something before this test's own run (23) even starts, so
    run_inputs is non-empty at the moment link_output_sync(SLUG, 23, first) is called. Without
    that row present, a broken WHERE clause that ignored run_id entirely would still find
    nothing to wrongly attach - an empty table looks correct whether the scoping is right or
    not - so this row is what makes the assertion below actually distinguish the two.
    """
    from agents.tools._db import link_output_sync, record_run_input_sync

    async with get_connection(SLUG) as conn:
        other_run_input = await _output(conn, "value_chain_mapper", "value_chain_model", 10)
    record_run_input_sync(SLUG, 99, other_run_input)

    async with get_connection(SLUG) as conn:
        first = await _output(conn, "interaction_designer", "interview_scripts", 7)
    link_output_sync(SLUG, 23, first)

    async with get_connection(SLUG) as conn:
        model = await _output(conn, "value_chain_mapper", "value_chain_model", 9)
    record_run_input_sync(SLUG, 23, model)

    async with get_connection(SLUG) as conn:
        rows = {r["output_id"]: r for r in await fetch_lineage(conn, project_id=1)}
    assert rows[first]["input_output_ids"] == []


# The tests above drive record_run_input_sync, record_run_document_sync and link_output_sync
# directly - proving the bookkeeping is correct in isolation, but not that either tool actually
# calls it. The three below go through SQLiteStateTool and ChromaQueryTool's public interface,
# _run(), so a dropped run_id or a wrong id passed at the call site would fail here even if
# every sync helper above stayed correct.


@pytest.mark.asyncio
async def test_a_tool_read_records_the_run_input(project):
    """SQLiteStateTool's read branch, not the sync helper called directly, must record what
    it served."""
    from agents.tools._db import insert_agent_output_sync
    from agents.tools.sqlite_state import SQLiteStateTool

    outputs_dir = project / "projects" / SLUG / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    file_path = outputs_dir / "value_chain_model.json"
    file_path.write_text('{"hello": "world"}')
    model_id = insert_agent_output_sync(
        SLUG, "value_chain_mapper", "value_chain_model", str(file_path)
    )

    tool = SQLiteStateTool(slug=SLUG, run_id=30)
    result = tool._run(
        operation="read", key="value_chain_model", agent_name="value_lever_analyst"
    )
    assert "hello" in result

    async with get_connection(SLUG) as conn:
        async with conn.execute(
            "SELECT 1 FROM run_inputs WHERE run_id=? AND output_id=?", (30, model_id)
        ) as cur:
            row = await cur.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_a_tool_write_links_to_what_the_same_run_read(project):
    """End to end: a read through the tool followed by a write through the tool, under the
    same run, must produce a durable output_lineage edge - the path this task exists to build,
    not just the sync helper that backs it."""
    import json

    from agents.tools._db import insert_agent_output_sync
    from agents.tools.sqlite_state import SQLiteStateTool

    outputs_dir = project / "projects" / SLUG / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    file_path = outputs_dir / "value_chain_model.json"
    file_path.write_text('{"hello": "world"}')
    model_id = insert_agent_output_sync(
        SLUG, "value_chain_mapper", "value_chain_model", str(file_path)
    )

    tool = SQLiteStateTool(slug=SLUG, agent_name="value_lever_analyst", run_id=31)
    tool._run(operation="read", key="value_chain_model", agent_name="value_lever_analyst")
    write_result = tool._run(
        operation="write", key="value_levers", agent_name="value_lever_analyst",
        value=json.dumps([{"lever": "x"}]),
    )
    assert "Written to" in write_result

    async with get_connection(SLUG) as conn:
        async with conn.execute(
            "SELECT id FROM agent_outputs WHERE output_type='value_levers'"
        ) as cur:
            levers_row = await cur.fetchone()
        async with conn.execute(
            "SELECT input_output_id FROM output_lineage WHERE output_id=?",
            (levers_row["id"],),
        ) as cur:
            edges = [r[0] async for r in cur]
    assert edges == [model_id]


@pytest.mark.asyncio
async def test_a_tool_query_records_the_run_document(project):
    """ChromaQueryTool's own recording, not record_run_document_sync called directly, must
    fire for a doc_id it actually serves."""
    from unittest.mock import MagicMock, patch

    from agents.tools.chroma_query import ChromaQueryTool

    async with get_connection(SLUG) as conn:
        await conn.execute(
            "INSERT INTO client_documents (id, project_id, filename, original_name,"
            " file_path, content_type, size_bytes) VALUES (7,1,'h.pdf','Report.pdf','x','p',1)"
        )
        await conn.commit()

    col = MagicMock()
    col.count.return_value = 1
    col.query.return_value = {
        "documents": [["Some retrieved text."]],
        "metadatas": [[{"doc_id": 7, "chunk": 1}]],
    }
    client = MagicMock()
    client.get_collection.return_value = col

    tool = ChromaQueryTool(slug=SLUG, sector="utilities", run_id=40)
    with patch("agents.tools.chroma_query.get_chroma_client", return_value=client), \
         patch("agents.tools.chroma_query._chroma_reachable", return_value=True):
        tool._run(query="asset condition", collection="project")

    async with get_connection(SLUG) as conn:
        async with conn.execute("SELECT run_id, doc_id FROM run_documents") as cur:
            rows = [tuple(r) async for r in cur]
    assert rows == [(40, 7)]


@pytest.mark.asyncio
async def test_a_tool_query_does_not_record_an_answer_id_as_a_run_document(project):
    """answer_id and doc_id are different namespaces. run_documents has a foreign key into
    client_documents, so an answer_id recorded there would be a dangling reference into the
    wrong table."""
    from unittest.mock import MagicMock, patch

    from agents.tools.chroma_query import ChromaQueryTool

    col = MagicMock()
    col.count.return_value = 1
    col.query.return_value = {
        "documents": [["For compliance, yes."]],
        "metadatas": [[{"answer_id": 812, "node_id": "1.2"}]],
    }
    client = MagicMock()
    client.get_collection.return_value = col

    tool = ChromaQueryTool(slug=SLUG, sector="utilities", run_id=41)
    with patch("agents.tools.chroma_query.get_chroma_client", return_value=client), \
         patch("agents.tools.chroma_query._chroma_reachable", return_value=True):
        tool._run(query="asset record", collection="interviews")

    async with get_connection(SLUG) as conn:
        async with conn.execute(
            "SELECT run_id, doc_id FROM run_documents WHERE run_id=41"
        ) as cur:
            rows = [tuple(r) async for r in cur]
    assert rows == []
