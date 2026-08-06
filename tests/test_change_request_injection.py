# tests/test_change_request_injection.py
"""Open change requests reach the agent's task, then stop.

A request injected on every subsequent run would grow the block without bound until it
crowded out the task it was attached to.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import yaml

from api.database import get_connection, insert_output_change, insert_project

SLUG = "injection-test"
CREW_SLUG = "injection-crew-test"


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


# ── build_and_run_crew: the injection and the close, not just the gathering ────────────
#
# The three tests above only exercise _fetch_change_requests directly - they prove the
# gathering is correct but say nothing about the control-flow guarantee that makes it matter:
# that the text actually lands on crew.tasks before kickoff, and that a failed run leaves the
# request untouched. The crew factory and crewai's Crew/Task are mocked at the same boundary
# tests/test_run_service.py already uses (patching the crew-creation function, and Crew.tasks /
# kickoff_async on the returned mock); _fetch_change_requests itself is never mocked, so these
# tests run the real gathering, the real injection loop, and the real close.


@pytest_asyncio.fixture
async def crew_project(tmp_path, monkeypatch):
    from api.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    projects_dir = tmp_path / "projects"
    monkeypatch.setenv("PROJECTS_DIR", str(projects_dir))
    project_dir = projects_dir / CREW_SLUG
    project_dir.mkdir(parents=True)
    (project_dir / "config.yaml").write_text(
        yaml.dump({"llm_mode": "standard", "sector": "utilities"})
    )
    async with get_connection(CREW_SLUG) as conn:
        await insert_project(
            conn, slug=CREW_SLUG, llm_mode="standard", sector="utilities", config_json="{}"
        )
    yield
    get_settings.cache_clear()


async def _requirements_output(conn, *, is_current=1, version=1):
    """An output for 'requirements_analyst', one of the requirements crew's agents."""
    cur = await conn.execute(
        "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
        " version, is_current, review_status)"
        " VALUES (1,'requirements_analyst','requirements_doc',?,?,?,'pending')",
        (f"r_v{version}.json", version, is_current),
    )
    await conn.commit()
    return cur.lastrowid


async def _change_status(output_id):
    async with get_connection(CREW_SLUG) as conn:
        async with conn.execute(
            "SELECT status, applied_run_id FROM output_changes WHERE output_id=?",
            (output_id,),
        ) as cur:
            return await cur.fetchone()


@pytest.mark.asyncio
async def test_change_request_text_reaches_the_task_before_kickoff(crew_project):
    """The prefixing is the behaviour the gathering function exists to enable.

    A mock task.description is inspected from inside kickoff_async's own side effect, so the
    assertion pins the ordering itself, not just that the mutation happened at some point.
    """
    async with get_connection(CREW_SLUG) as conn:
        output_id = await _requirements_output(conn)
        await insert_output_change(
            conn, output_id=output_id, requested_by="alice", source="review",
            request="use the new tariff formula", summary="", kind="change_request",
        )

    mock_task = MagicMock()
    mock_task.description = "original task body"
    mock_crew = MagicMock()
    mock_crew.tasks = [mock_task]
    seen_at_kickoff: list[str] = []

    async def _fake_kickoff():
        seen_at_kickoff.append(mock_task.description)
        return "done"

    mock_crew.kickoff_async = AsyncMock(side_effect=_fake_kickoff)

    import agents.crews.requirements_crew  # noqa: F401  ensure importable before patching
    with patch(
        "agents.crews.requirements_crew.create_requirements_crew",
        return_value=mock_crew,
    ):
        from api.services.run_service import build_and_run_crew
        result = await build_and_run_crew(CREW_SLUG, "requirements", run_id=7)

    assert result == "done"
    assert len(seen_at_kickoff) == 1
    assert "use the new tariff formula" in seen_at_kickoff[0]
    assert seen_at_kickoff[0].endswith("\n\noriginal task body")

    row = await _change_status(output_id)
    assert row["status"] == "applied"
    assert row["applied_run_id"] == 7


@pytest.mark.asyncio
async def test_a_failed_run_leaves_the_change_request_open(crew_project):
    """The guarantee that matters: a raised kickoff never reaches the close."""
    async with get_connection(CREW_SLUG) as conn:
        output_id = await _requirements_output(conn)
        await insert_output_change(
            conn, output_id=output_id, requested_by="alice", source="review",
            request="fix the units", summary="", kind="change_request",
        )

    mock_task = MagicMock()
    mock_task.description = "original task body"
    mock_crew = MagicMock()
    mock_crew.tasks = [mock_task]
    mock_crew.kickoff_async = AsyncMock(side_effect=RuntimeError("boom"))

    import agents.crews.requirements_crew  # noqa: F401  ensure importable before patching
    with patch(
        "agents.crews.requirements_crew.create_requirements_crew",
        return_value=mock_crew,
    ):
        from api.services.run_service import build_and_run_crew
        with pytest.raises(RuntimeError, match="boom"):
            await build_and_run_crew(CREW_SLUG, "requirements", run_id=9)

    row = await _change_status(output_id)
    assert row["status"] == "open"
    assert row["applied_run_id"] is None
