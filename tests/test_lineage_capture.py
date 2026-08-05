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
    ever wrote would claim an output was built from something written after it."""
    from agents.tools._db import link_output_sync, record_run_input_sync

    async with get_connection(SLUG) as conn:
        first = await _output(conn, "interaction_designer", "interview_scripts", 7)
    link_output_sync(SLUG, 23, first)

    async with get_connection(SLUG) as conn:
        model = await _output(conn, "value_chain_mapper", "value_chain_model", 9)
    record_run_input_sync(SLUG, 23, model)

    async with get_connection(SLUG) as conn:
        rows = {r["output_id"]: r for r in await fetch_lineage(conn, project_id=1)}
    assert rows[first]["input_output_ids"] == []
