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
    classify_downstream,
    downstream_of,
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
        report = await readiness_report(conn)
    assert report["discovery_mapping"]["ready"] is True


@pytest.mark.asyncio
async def test_a_crew_waits_until_every_upstream_is_committed(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, insert_approval_commit

    async with get_connection("graph-test") as conn:
        # discovery_interviews needs assessment_design AND stakeholder_management.
        before = await readiness_report(conn)

        await insert_approval_commit(
            conn, crew_name="assessment_design", committed_by="admin"
        )
        halfway = await readiness_report(conn)

        await insert_approval_commit(
            conn, crew_name="stakeholder_management", committed_by="admin"
        )
        after = await readiness_report(conn)

    assert before["discovery_interviews"]["ready"] is False
    assert halfway["discovery_interviews"]["ready"] is False
    assert halfway["discovery_interviews"]["waiting_on"] == ["stakeholder_management"]
    assert after["discovery_interviews"]["ready"] is True


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


@pytest.mark.asyncio
async def test_a_downstream_crew_with_all_upstreams_committed_is_ready(client):
    """discovery_mapping is assessment_design's only upstream, so committing it arms Maya."""
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, insert_approval_commit

    async with get_connection("graph-test") as conn:
        await insert_approval_commit(conn, crew_name="discovery_mapping", committed_by="a")

        result = await classify_downstream(conn, crew_name="discovery_mapping")

    assert "assessment_design" in result["ready"]


@pytest.mark.asyncio
async def test_a_crew_stays_ready_on_a_second_commit_upstream(client):
    """The behaviour this whole project turns on. The old 'released' idea reported a crew
    only the first time it became ready, so a revision approved later started nothing.
    Readiness is a state, not a transition."""
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, insert_approval_commit

    async with get_connection("graph-test") as conn:
        await insert_approval_commit(conn, crew_name="discovery_mapping", committed_by="a")
        first = await classify_downstream(conn, crew_name="discovery_mapping")

        await insert_approval_commit(conn, crew_name="discovery_mapping", committed_by="a")
        second = await classify_downstream(conn, crew_name="discovery_mapping")

    assert "assessment_design" in first["ready"]
    assert "assessment_design" in second["ready"]


@pytest.mark.asyncio
async def test_a_crew_with_an_uncommitted_upstream_is_waiting_and_names_it(client):
    """discovery_interviews needs BOTH assessment_design and stakeholder_management. A
    single-upstream crew cannot discriminate 'ready' from 'its one upstream just landed',
    so this case must be built on a two-upstream crew or it proves nothing."""
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, insert_approval_commit

    async with get_connection("graph-test") as conn:
        await insert_approval_commit(conn, crew_name="assessment_design", committed_by="a")

        result = await classify_downstream(conn, crew_name="assessment_design")

    waiting = {w["crew"]: w["waiting_on"] for w in result["waiting"]}
    assert "discovery_interviews" in waiting
    assert waiting["discovery_interviews"] == ["stakeholder_management"]
    assert "discovery_interviews" not in result["ready"]


@pytest.mark.asyncio
async def test_a_crew_becomes_ready_once_its_last_upstream_lands(client):
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, insert_approval_commit

    async with get_connection("graph-test") as conn:
        await insert_approval_commit(conn, crew_name="assessment_design", committed_by="a")
        await insert_approval_commit(conn, crew_name="stakeholder_management", committed_by="a")

        result = await classify_downstream(conn, crew_name="stakeholder_management")

    assert "discovery_interviews" in result["ready"]


@pytest.mark.asyncio
async def test_a_ready_crew_that_is_running_is_classified_running_not_ready(client):
    """Two concurrent runs of one crew both writing versioned outputs is the failure this
    avoids. A running crew must not also appear in ready, or the caller starts it twice."""
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, insert_approval_commit, insert_crew_run, fetch_project

    async with get_connection("graph-test") as conn:
        project = await fetch_project(conn, slug="graph-test")
        await insert_approval_commit(conn, crew_name="discovery_mapping", committed_by="a")
        await insert_crew_run(
            conn, project_id=project["id"], crew_name="assessment_design", status="running"
        )

        result = await classify_downstream(conn, crew_name="discovery_mapping")

    assert "assessment_design" in result["running"]
    assert "assessment_design" not in result["ready"]


@pytest.mark.asyncio
async def test_every_downstream_crew_appears_exactly_once(client):
    """A crew silently in no list is a crew nobody can see is stuck."""
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection, insert_approval_commit

    async with get_connection("graph-test") as conn:
        await insert_approval_commit(conn, crew_name="assessment_design", committed_by="a")

        result = await classify_downstream(conn, crew_name="assessment_design")

    seen = result["ready"] + result["running"] + [w["crew"] for w in result["waiting"]]
    assert sorted(seen) == sorted(downstream_of("assessment_design"))
    assert len(seen) == len(set(seen))


@pytest.mark.asyncio
async def test_a_crew_with_no_downstream_classifies_to_three_empty_lists(client):
    """business_plan is the end of the chain. Committing it must not error."""
    await client.post("/projects", json=PROJECT)
    from api.database import get_connection

    async with get_connection("graph-test") as conn:
        result = await classify_downstream(conn, crew_name="business_plan")

    assert result == {"ready": [], "running": [], "waiting": []}


# ---------------------------------------------------------------------------
# The sequence after the interviews.
#
# Each crew consumes what the one before it produced: themes to propositions, propositions
# to capability uplift, initiatives to requirements, requirements to a roadmap.
# ---------------------------------------------------------------------------


def test_requirements_waits_for_the_capabilities_that_scope_it():
    # It had NO dependencies at all, so it could run before the interviews it is meant to
    # follow. That made the displayed order a fiction rather than a plan.
    assert CREW_DEPENDENCIES["discovery"] == ["architecture"]


def test_value_design_no_longer_waits_for_requirements():
    """Value propositions come from Casey's themes. Waiting on a crew that now runs two
    steps later would deadlock the board outright - every crew waiting, none ever ready."""
    assert CREW_DEPENDENCIES["value_design"] == ["discovery_interviews"]


def test_delivery_waits_for_requirements_not_for_capabilities():
    # The roadmap needs the complexity, method and cost that requirements produces, not
    # only the initiatives above it.
    assert CREW_DEPENDENCIES["delivery"] == ["discovery"]


def _crew_order_from_frontend() -> list[str]:
    """CREW_ORDER as the frontend declares it.

    Read rather than duplicated: mirroring the graph into a TypeScript fixture would make
    two declarations of one sequence, which is the very drift this test exists to catch.
    """
    import re

    source = Path("ui/src/components/agentStatus.ts").read_text()
    block = re.search(r"export const CREW_ORDER = \[(.*?)\]", source, re.S)
    assert block, "CREW_ORDER not found - has it been renamed?"
    return re.findall(r"'([a-z_]+)'", block.group(1))


def test_the_displayed_order_is_one_the_graph_permits():
    """Two declarations of one sequence: the graph enforces, the order displays. An order
    contradicting the graph shows a crew as next when it cannot run, which is worse than
    showing nothing - the reader acts on it and the run is refused."""
    order = _crew_order_from_frontend()
    assert set(order) == set(CREW_DEPENDENCIES), "the two disagree about which crews exist"
    for position, crew in enumerate(order):
        for upstream in CREW_DEPENDENCIES[crew]:
            assert order.index(upstream) < position, (
                f"{crew} is displayed before its dependency {upstream}"
            )
