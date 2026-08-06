# tests/test_output_change_lifecycle.py
"""A change request is injected once, then never again.

Without a lifecycle every run carries every request ever made, and the block that carries
them grows until it crowds out the task it is attached to.
"""
import pytest
import pytest_asyncio

from api.database import (
    fetch_open_change_requests,
    get_connection,
    insert_output_change,
    insert_project,
    mark_change_requests_applied,
)

SLUG = "change-lifecycle-test"


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


async def _output(conn, output_type="value_chain_model", version=1):
    cur = await conn.execute(
        "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
        " version, is_current, review_status) VALUES (1,'value_chain_mapper',?,?,?,1,'pending')",
        (output_type, f"{output_type}_v{version}.json", version),
    )
    await conn.commit()
    return cur.lastrowid


@pytest.mark.asyncio
async def test_a_new_change_defaults_to_unclassified_and_open(project):
    """An unexplained manual edit must land somewhere, not nowhere."""
    async with get_connection(SLUG) as conn:
        output_id = await _output(conn)
        change_id = await insert_output_change(
            conn, output_id=output_id, requested_by="alice", source="edit",
            request="trimmed the summary", summary="",
        )
        row = await conn.execute_fetchall(
            "SELECT kind, status FROM output_changes WHERE id=?", (change_id,)
        )

    assert tuple(row[0]) == ("unclassified", "open")


@pytest.mark.asyncio
async def test_only_change_requests_are_fetched_for_injection(project):
    """A correction reaches the agent through RAG and a skill through the prompt library.
    Injecting them here as well would say the same thing twice, in the wrong voice."""
    async with get_connection(SLUG) as conn:
        output_id = await _output(conn)
        for kind in ("change_request", "correction", "skill", "unclassified"):
            await insert_output_change(
                conn, output_id=output_id, requested_by="alice", source="review",
                request=f"a {kind}", summary="", kind=kind,
            )
        rows = await fetch_open_change_requests(conn, output_ids=[output_id])

    assert [r["request"] for r in rows] == ["a change_request"]


@pytest.mark.asyncio
async def test_an_applied_request_is_not_fetched_again(project):
    async with get_connection(SLUG) as conn:
        output_id = await _output(conn)
        change_id = await insert_output_change(
            conn, output_id=output_id, requested_by="alice", source="review",
            request="use the approved figures", summary="", kind="change_request",
        )
        first = await fetch_open_change_requests(conn, output_ids=[output_id])
        marked = await mark_change_requests_applied(
            conn, change_ids=[change_id], run_id=77
        )
        second = await fetch_open_change_requests(conn, output_ids=[output_id])
        row = await conn.execute_fetchall(
            "SELECT status, applied_run_id FROM output_changes WHERE id=?", (change_id,)
        )

    assert len(first) == 1
    assert marked == 1
    assert second == []
    assert tuple(row[0]) == ("applied", 77)


@pytest.mark.asyncio
async def test_marking_nothing_is_safe(project):
    """The caller marks whatever it injected. Injecting nothing is the ordinary case on a
    first run, and must not raise or build an empty IN () clause."""
    async with get_connection(SLUG) as conn:
        assert await mark_change_requests_applied(conn, change_ids=[], run_id=77) == 0
