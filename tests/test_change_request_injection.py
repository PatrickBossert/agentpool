# tests/test_change_request_injection.py
"""Open change requests reach the agent's task, then stop.

A request injected on every subsequent run would grow the block without bound until it
crowded out the task it was attached to.
"""
import pytest
import pytest_asyncio

from api.database import get_connection, insert_output_change, insert_project

SLUG = "injection-test"


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
    yield
    get_settings.cache_clear()


async def _output(conn, *, is_current=1, version=1):
    cur = await conn.execute(
        "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
        " version, is_current, review_status)"
        " VALUES (1,'value_chain_mapper','value_chain_model',?,?,?,'pending')",
        (f"m_v{version}.json", version, is_current),
    )
    await conn.commit()
    return cur.lastrowid


@pytest.mark.asyncio
async def test_open_requests_are_gathered_for_the_crew(project):
    from api.services.run_service import _fetch_change_requests

    async with get_connection(SLUG) as conn:
        output_id = await _output(conn)
        await insert_output_change(
            conn, output_id=output_id, requested_by="alice", source="review",
            request="use the approved figures", summary="", kind="change_request",
        )

    text, ids = await _fetch_change_requests(SLUG, "discovery_mapping")

    assert "use the approved figures" in text
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_a_request_against_a_superseded_output_is_not_replayed(project):
    """Scoped to current outputs, matching how commit_service already scopes them."""
    from api.services.run_service import _fetch_change_requests

    async with get_connection(SLUG) as conn:
        old = await _output(conn, is_current=0, version=1)
        await _output(conn, is_current=1, version=2)
        await insert_output_change(
            conn, output_id=old, requested_by="alice", source="review",
            request="an old request", summary="", kind="change_request",
        )

    text, ids = await _fetch_change_requests(SLUG, "discovery_mapping")

    assert text == ""
    assert ids == []


@pytest.mark.asyncio
async def test_a_crew_with_no_requests_gathers_nothing(project):
    """The ordinary first run. Must return empty rather than an empty heading."""
    from api.services.run_service import _fetch_change_requests

    async with get_connection(SLUG) as conn:
        await _output(conn)

    text, ids = await _fetch_change_requests(SLUG, "discovery_mapping")

    assert text == ""
    assert ids == []
