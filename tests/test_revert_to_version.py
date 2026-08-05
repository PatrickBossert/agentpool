# tests/test_revert_to_version.py
"""Reverting to an earlier output version must succeed even when the newer version has
lineage, citation, or run-input rows referencing it - foreign_keys=ON means those rows
must be cleared before agent_outputs can be hard-deleted."""
import pytest
import pytest_asyncio

from api.database import get_connection, insert_project, revert_to_version

SLUG = "revert-lineage-test"


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
async def test_revert_succeeds_when_the_discarded_version_has_lineage_rows(project):
    async with get_connection(SLUG) as conn:
        # v1 is the target we will revert back to.
        v1 = await _output(conn, "value_chain_mapper", "value_chain_model", 1, is_current=0)
        # v2 is the doomed version - current now, deleted by the revert.
        v2 = await _output(conn, "value_chain_mapper", "value_chain_model", 2, is_current=1)
        # An unrelated output that v2 was built from, and one built from v2 - covers
        # output_lineage in both directions.
        upstream = await _output(conn, "value_lever_analyst", "value_levers", 1, is_current=1)
        downstream = await _output(conn, "interaction_designer", "interview_scripts", 1, is_current=1)

        # v2 was built from `upstream` (v2 is the output_id, upstream is the input).
        await conn.execute(
            "INSERT INTO output_lineage (output_id, input_output_id) VALUES (?,?)",
            (v2, upstream),
        )
        # `downstream` was built from v2 (downstream is the output_id, v2 is the input).
        await conn.execute(
            "INSERT INTO output_lineage (output_id, input_output_id) VALUES (?,?)",
            (downstream, v2),
        )

        await conn.execute(
            "INSERT INTO client_documents (id, project_id, filename, original_name,"
            " file_path, content_type, size_bytes) VALUES (9,1,'a.pdf','Annual.pdf','x','p',1)"
        )
        await conn.execute(
            "INSERT INTO output_citations (output_id, doc_id) VALUES (?,9)", (v2,)
        )

        await conn.execute(
            "INSERT INTO run_inputs (run_id, output_id) VALUES (50,?)", (v2,)
        )
        await conn.commit()

    async with get_connection(SLUG) as conn:
        row, deleted_paths = await revert_to_version(conn, project_id=1, output_id=v1)

    assert row is not None
    assert row["id"] == v1
    assert row["is_current"] == 1
    assert deleted_paths == ["value_chain_model_v2.json"]

    async with get_connection(SLUG) as conn:
        async with conn.execute(
            "SELECT id, is_current FROM agent_outputs WHERE output_type='value_chain_model'"
        ) as cur:
            remaining = await cur.fetchall()
    assert [dict(r) for r in remaining] == [{"id": v1, "is_current": 1}]


@pytest.mark.asyncio
async def test_revert_supersedes_by_output_type_not_by_agent(project):
    """Version numbering and is_current supersession are scoped by (project, output_type),
    not by agent - the filename that anchors a version carries no agent (Task 3). Two agents
    can both write the 'state' output type; reverting alex's output to an earlier version
    must leave exactly one is_current row for the output type, superseding maya's row too -
    not leave two current rows standing side by side."""
    async with get_connection(SLUG) as conn:
        alex_v1 = await _output(conn, "alex", "state", 1, is_current=0)
        alex_v2 = await _output(conn, "alex", "state", 2, is_current=0)
        maya_v3 = await _output(conn, "maya", "state", 3, is_current=1)

    async with get_connection(SLUG) as conn:
        row, deleted_paths = await revert_to_version(conn, project_id=1, output_id=alex_v1)

    assert row is not None
    assert row["id"] == alex_v1
    assert row["is_current"] == 1
    assert deleted_paths == ["state_v2.json", "state_v3.json"]

    async with get_connection(SLUG) as conn:
        async with conn.execute(
            "SELECT id, is_current FROM agent_outputs WHERE output_type='state' ORDER BY id"
        ) as cur:
            remaining = await cur.fetchall()
    remaining = [dict(r) for r in remaining]
    assert remaining == [{"id": alex_v1, "is_current": 1}]
    assert sum(r["is_current"] for r in remaining) == 1
