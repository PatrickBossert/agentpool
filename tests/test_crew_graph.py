# tests/test_crew_graph.py
"""Which crews may run, derived from what has been committed.

Readiness is computed rather than stored: a stored flag would need invalidating on
every commit, and a stale one would arm a crew whose inputs had been withdrawn.
"""
import pytest
from pathlib import Path

from api.config import get_settings
from api.services.crew_graph import (
    CREW_DEPENDENCIES,
    downstream_of,
    is_crew_ready,
    readiness_report,
)

PROJECT = {
    "client_slug": "graph-test",
    "llm_mode": "standard",
    "sector": "transport",
    "stakeholder_groups": ["Operations"],
    "value_stream_labels": ["Asset Mgmt"],
    "crews_enabled": ["discovery"],
    "review_gates": True,
    "slack_channel": "",
}


@pytest.fixture(autouse=True)
def clean():
    settings = get_settings()
    db_path = Path(settings.database_dir) / "graph-test.db"
    db_path.unlink(missing_ok=True)
    yield
    get_settings.cache_clear()
    db_path.unlink(missing_ok=True)


def test_every_dispatchable_crew_appears_in_the_graph():
    """A crew missing from the graph would be permanently unready with no signal."""
    from api.services.run_service import _CREW_AGENT_NAMES
    assert set(CREW_DEPENDENCIES) == set(_CREW_AGENT_NAMES)


def test_every_named_dependency_is_itself_a_crew():
    for crew, upstreams in CREW_DEPENDENCIES.items():
        for upstream in upstreams:
            assert upstream in CREW_DEPENDENCIES, f"{crew} depends on unknown {upstream}"


def test_the_graph_is_acyclic():
    """A cycle would make both crews permanently unready and is invisible by eye."""
    visiting, done = set(), set()

    def visit(crew: str, trail: list[str]) -> None:
        if crew in done:
            return
        assert crew not in visiting, f"cycle: {' -> '.join(trail + [crew])}"
        visiting.add(crew)
        for upstream in CREW_DEPENDENCIES[crew]:
            visit(upstream, trail + [crew])
        visiting.discard(crew)
        done.add(crew)

    for crew in CREW_DEPENDENCIES:
        visit(crew, [])


def test_jordan_now_follows_maya():
    """The reordering: stakeholder_management depends on assessment_design."""
    assert "assessment_design" in CREW_DEPENDENCIES["stakeholder_management"]


def test_downstream_is_the_inverse_of_dependencies():
    assert "assessment_design" in downstream_of("discovery_mapping")
    assert downstream_of("business_plan") == []


@pytest.mark.asyncio
async def test_a_crew_with_no_dependencies_is_always_ready(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection
    async with get_connection("graph-test") as conn:
        assert await is_crew_ready(conn, crew_name="discovery_mapping") is True


@pytest.mark.asyncio
async def test_a_crew_waits_until_every_upstream_is_committed(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, insert_approval_commit

    async with get_connection("graph-test") as conn:
        # discovery_interviews needs assessment_design AND stakeholder_management.
        assert await is_crew_ready(conn, crew_name="discovery_interviews") is False

        await insert_approval_commit(
            conn, crew_name="assessment_design", committed_by="admin"
        )
        assert await is_crew_ready(conn, crew_name="discovery_interviews") is False

        await insert_approval_commit(
            conn, crew_name="stakeholder_management", committed_by="admin"
        )
        assert await is_crew_ready(conn, crew_name="discovery_interviews") is True


@pytest.mark.asyncio
async def test_the_report_names_what_each_crew_is_waiting_on(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, insert_approval_commit

    async with get_connection("graph-test") as conn:
        await insert_approval_commit(
            conn, crew_name="assessment_design", committed_by="admin"
        )
        report = await readiness_report(conn)

    assert report["discovery_mapping"]["ready"] is True
    assert report["discovery_interviews"]["ready"] is False
    assert report["discovery_interviews"]["waiting_on"] == ["stakeholder_management"]
