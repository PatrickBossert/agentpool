# tests/test_assignment_coverage.py
"""Coverage of the stakeholder mapping: reported to Jordan, raised by Pamela past a tenth.

Two proportions, and they are asserted **independently and against real rows**. One shared
threshold check would let a chain nobody speaks for and a roster nobody has placed arrive as the
same fact, and this project has shipped five tests that verified a property one layer away from
where it holds - so the figures here are compared with assignments actually written to the table
and nodes actually written to the registry, never with a second copy of the arithmetic.

The last group is the one the whole slice exists for. The mapping being stored, durable and
makeable by hand still left the Stakeholder Manager unable to read it: his task told him to fetch
`stakeholder_assignments` through `SQLiteStateTool`, which resolves a key through `agent_outputs`
and can only ever see an output type. Those tests drive `build_and_run_crew` and read the task
description the agent is actually handed.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from crewai import LLM

from api.config import get_settings
from api.database import (
    fetch_project,
    fetch_stakeholder_assignments,
    get_connection,
    insert_crew_run,
    insert_orchestration_run,
    insert_project,
    insert_stakeholder,
    replace_stakeholder_assignments,
)
from api.services.assignment_coverage import (
    COVERAGE_MISMATCH_THRESHOLD,
    build_assignment_coverage,
)

SLUG = "coverage-probe"


def _write_registry(projects_dir: Path, activities: list[dict]) -> None:
    outputs = projects_dir / SLUG / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "value_chain_registry.json").write_text(
        json.dumps({"schema_version": 2, "activities": activities}), encoding="utf-8"
    )


def _nodes(count: int, *, first: int = 1, active: bool = True) -> list[dict]:
    return [
        {"id": f"1.{n}", "label": f"Activity {n}", "level": "L2", "active": active}
        for n in range(first, first + count)
    ]


@pytest_asyncio.fixture
async def project(tmp_path, monkeypatch):
    """Its own DATABASE_DIR and PROJECTS_DIR.

    The shared /tmp/agentpool_test survives between runs, so a test leaning on it passes once
    and fails ever after - the defect that shipped through eight reviews on this project.
    """
    db_dir = tmp_path / "data"
    projects_dir = tmp_path / "projects"
    db_dir.mkdir(parents=True, exist_ok=True)
    projects_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATABASE_DIR", str(db_dir))
    monkeypatch.setenv("PROJECTS_DIR", str(projects_dir))
    get_settings.cache_clear()

    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="rail",
            config_json='{"interview_method": "agent"}',
        )
        row = await fetch_project(conn, slug=SLUG)

    yield {"id": row["id"], "projects_dir": projects_dir}
    get_settings.cache_clear()


async def _people(project_id: int, count: int, *, synthetic: int = 0) -> list[int]:
    """`count` stakeholders, the last `synthetic` of them marked as seeded.

    `is_synthetic` is set with raw SQL because no ordinary door can set it - `insert_stakeholder`
    takes no such parameter, which is what makes the marker un-undoable in production.
    """
    ids: list[int] = []
    async with get_connection(SLUG) as conn:
        for n in range(count):
            ids.append(await insert_stakeholder(
                conn, project_id=project_id, name=f"Person {n}", job_title=f"Role {n}"
            ))
        for stakeholder_id in ids[len(ids) - synthetic:] if synthetic else []:
            await conn.execute(
                "UPDATE stakeholders SET is_synthetic=1 WHERE id=?", (stakeholder_id,)
            )
        await conn.commit()
    return ids


async def _assign(project_id: int, pairs: list[tuple[int, str]]) -> None:
    async with get_connection(SLUG) as conn:
        await replace_stakeholder_assignments(
            conn,
            project_id=project_id,
            assignments=[{"stakeholder_id": s, "node_id": n} for s, n in pairs],
        )


async def _coverage(project_id: int) -> dict:
    async with get_connection(SLUG) as conn:
        return await build_assignment_coverage(conn, slug=SLUG, project_id=project_id)


async def _report_issues(project_id: int) -> list[dict]:
    """Pamela's coverage issues alone, from the report she would actually publish."""
    from api.services.pam_report_service import build_pam_report

    report = await build_pam_report(SLUG)
    return [i for i in report["issues"] if i["crew"] == "stakeholder_management"]


async def _dispatch_interviews(project_id: int) -> list[dict]:
    """Run the `discovery_interviews` dispatch and return what it fed the crew.

    The second consumer of the same derivation, and the one where "who is assigned" becomes
    "who gets a session". Asserted through the dispatch rather than off the coverage dict,
    because that is the layer at which a person reaches an interview.
    """
    async with get_connection(SLUG) as conn:
        orch_run_id = await insert_orchestration_run(conn, project_id=project_id)
        crew_run_id = await insert_crew_run(
            conn, project_id=project_id, crew_name="discovery_interviews",
            status="running", orchestration_run_id=orch_run_id,
        )

    crew = MagicMock()
    crew.kickoff_async = AsyncMock(return_value="done")

    with patch(
        "api.services.run_service.load_project_config",
        return_value={"sector": "rail", "interview_method": "agent"},
    ), patch(
        "agents.crews.discovery_interviews_crew.create_discovery_interviews_crew",
        return_value=crew,
    ) as factory:
        from api.services.run_service import build_and_run_crew
        await build_and_run_crew(SLUG, "discovery_interviews", crew_run_id)

    return factory.call_args.kwargs["stakeholder_assignments"]


# ── The proportions, against rows rather than against a second computation ─────


@pytest.mark.asyncio
async def test_an_activity_with_nobody_is_counted_against_the_active_registry(project):
    """Four activities exist and three carry somebody, so one in four is a gap.

    The denominator is read from the registry and the numerator from the assignment table;
    neither is a number this test hands to the code it is testing.
    """
    _write_registry(project["projects_dir"], _nodes(4))
    people = await _people(project["id"], 3)
    await _assign(project["id"], [
        (people[0], "1.1"), (people[1], "1.2"), (people[2], "1.3"),
    ])

    coverage = await _coverage(project["id"])

    assert coverage["activities_total"] == 4
    assert coverage["activities_covered"] == 3
    assert coverage["activities_uncovered"] == 1
    assert coverage["uncovered_node_ids"] == ["1.4"]
    assert coverage["uncovered_proportion"] == 0.25


@pytest.mark.asyncio
async def test_a_retired_activity_is_not_a_gap(project):
    """`active` is the registry's own flag. A node nobody speaks for because it is no longer
    part of the chain is not a hole in the interview programme."""
    _write_registry(project["projects_dir"], _nodes(2) + [
        {"id": "9.9", "label": "Retired", "level": "L2", "active": False},
    ])
    people = await _people(project["id"], 2)
    await _assign(project["id"], [(people[0], "1.1"), (people[1], "1.2")])

    coverage = await _coverage(project["id"])

    assert coverage["activities_total"] == 2
    assert coverage["uncovered_node_ids"] == []
    assert coverage["uncovered_proportion"] == 0.0


# ── A retired activity is not somewhere a person can be placed ────────────────
#
# Three separate consequences of one rule, each asserted alone: the roster proportion, what
# reaches the crew, and the fact that the row is still reported. The first was a live defect -
# the activity denominator filtered on `active` and the roster one did not, so whoever spoke only
# for a retired activity counted as placed and vanished from the only list that says who will not
# be asked anything.


@pytest.mark.asyncio
async def test_retiring_an_activity_breaks_the_assignment_against_it(project):
    """The transition, not the state.

    A test that only sets up an already-retired node passes against a hard-coded filter and
    proves nothing about the rule. This places somebody on a live activity, watches the
    assignment work, then retires the activity underneath them - one registry rewrite, which
    is what Alex does on every run - and asserts all three consequences at once: they become
    unassigned, they appear in the unplaced list, and the crew is handed nothing for them.

    Read at the point of use rather than caught at retirement. There is no retirement event
    to catch - the mapper re-emits the whole chain every run - so the alternative would be
    hunting every path that can flip `active`, and this one is right again by itself if a
    node is ever brought back.
    """
    live = [
        {"id": "1.1", "label": "Live", "level": "L2", "active": True},
        {"id": "1.2", "label": "Doomed", "level": "L2", "active": True},
    ]
    _write_registry(project["projects_dir"], live)
    people = await _people(project["id"], 2)
    await _assign(project["id"], [(people[0], "1.1"), (people[1], "1.2")])

    before = await _coverage(project["id"])
    assert before["stakeholders_unassigned"] == 0
    assert [a["node_id"] for a in await _dispatch_interviews(project["id"])] == ["1.1", "1.2"]

    _write_registry(project["projects_dir"], [
        live[0], {**live[1], "active": False},
    ])

    after = await _coverage(project["id"])
    assert after["stakeholders_unassigned"] == 1
    assert [s["id"] for s in after["unassigned_stakeholders"]] == [people[1]]
    assert after["unassigned_proportion"] == 0.5
    assert [a["node_id"] for a in after["off_chain_assignments"]] == ["1.2"]
    assert [a["node_id"] for a in await _dispatch_interviews(project["id"])] == ["1.1"]

    # And the row itself is still there. The ledger may grow and may retire, but may never
    # forget: somebody placed that person deliberately, and erasing it would lose the fact.
    async with get_connection(SLUG) as conn:
        stored = await fetch_stakeholder_assignments(conn, project_id=project["id"])
    assert sorted(a["node_id"] for a in stored) == ["1.1", "1.2"]


@pytest.mark.asyncio
async def test_a_person_assigned_only_to_a_retired_activity_is_not_placed(project):
    _write_registry(project["projects_dir"], [
        {"id": "1.1", "label": "Live", "level": "L2", "active": True},
        {"id": "9.9", "label": "Retired", "level": "L2", "active": False},
    ])
    people = await _people(project["id"], 2)
    await _assign(project["id"], [(people[0], "1.1"), (people[1], "9.9")])

    coverage = await _coverage(project["id"])

    assert coverage["stakeholders_unassigned"] == 1
    assert [s["id"] for s in coverage["unassigned_stakeholders"]] == [people[1]]
    assert coverage["unassigned_proportion"] == 0.5
    assert coverage["stakeholders_assigned"] == 1


@pytest.mark.asyncio
async def test_an_assignment_to_a_retired_activity_does_not_reach_the_interviews(project):
    """The dispatch path handed the crew every row regardless, so the Interview Coordinator
    planned a session against a node no longer in the chain."""
    _write_registry(project["projects_dir"], [
        {"id": "1.1", "label": "Live", "level": "L2", "active": True},
        {"id": "9.9", "label": "Retired", "level": "L2", "active": False},
    ])
    people = await _people(project["id"], 2)
    await _assign(project["id"], [(people[0], "1.1"), (people[1], "9.9")])

    delivered = await _dispatch_interviews(project["id"])

    assert [a["node_id"] for a in delivered] == ["1.1"]
    assert [a["stakeholder_id"] for a in delivered] == [people[0]]


@pytest.mark.asyncio
async def test_a_retired_assignment_is_reported_to_the_agent_rather_than_dropped(project):
    """Excluded from the mapping and from both figures, and still named. Somebody made it on
    purpose, and it is the clearest evidence there is that the chain moved under the mapping."""
    _write_registry(project["projects_dir"], [
        {"id": "1.1", "label": "Live", "level": "L2", "active": True},
        {"id": "9.9", "label": "Retired Billing", "level": "L2", "active": False},
    ])
    async with get_connection(SLUG) as conn:
        placed = await insert_stakeholder(
            conn, project_id=project["id"], name="Placed Person", job_title="Ops"
        )
        stranded = await insert_stakeholder(
            conn, project_id=project["id"], name="Stranded Person", job_title="Billing"
        )
    await _assign(project["id"], [(placed, "1.1"), (stranded, "9.9")])

    description = await _task_description(project["id"])

    assert "ASSIGNED TO ACTIVITIES THAT ARE NOT IN THE ACTIVE CHAIN" in description
    assert "Stranded Person - 9.9 (Retired Billing)" in description
    assert "1 of 2 on the roster (50.0%)" in description


@pytest.mark.asyncio
async def test_an_unavailable_registry_does_not_unplace_the_whole_roster(project):
    """An absent registry is unknown, not empty.

    `get_value_chain_node_index` answers `{}` when the current output cannot be resolved as
    well as before the mapper has ever run. Reading that as "every node is retired" would
    strand every assignment, empty what the interviews are given, and raise a 100% issue
    against a mapping that is perfectly good.
    """
    people = await _people(project["id"], 2)
    await _assign(project["id"], [(people[0], "1.1"), (people[1], "1.2")])

    coverage = await _coverage(project["id"])

    assert coverage["off_chain_assignments"] == []
    assert coverage["stakeholders_unassigned"] == 0
    assert coverage["unassigned_proportion"] == 0.0
    assert [a["node_id"] for a in await _dispatch_interviews(project["id"])] == ["1.1", "1.2"]
    assert await _report_issues(project["id"]) == []


@pytest.mark.asyncio
async def test_an_id_the_registry_never_held_is_treated_as_off_chain_too(project):
    """Retired and unknown are one rule, because the consequence is identical - nobody is
    interviewed about either - and two rules would drift."""
    _write_registry(project["projects_dir"], _nodes(2))
    people = await _people(project["id"], 2)
    await _assign(project["id"], [(people[0], "1.1"), (people[1], "7.7.7")])

    coverage = await _coverage(project["id"])

    assert [a["node_id"] for a in coverage["off_chain_assignments"]] == ["7.7.7"]
    assert coverage["off_chain_total"] == 1
    assert coverage["stakeholders_unassigned"] == 1
    # The label falls back to the id, which is how an unknown id stays distinguishable from a
    # retired one that still carries its registry label.
    assert coverage["off_chain_assignments"][0]["node_label"] == "7.7.7"


@pytest.mark.asyncio
async def test_the_roster_direction_counts_people_placed_nowhere(project):
    _write_registry(project["projects_dir"], _nodes(2))
    people = await _people(project["id"], 4)
    await _assign(project["id"], [(people[0], "1.1"), (people[1], "1.2")])

    coverage = await _coverage(project["id"])

    assert coverage["roster_total"] == 4
    assert coverage["stakeholders_assigned"] == 2
    assert coverage["stakeholders_unassigned"] == 2
    assert [s["id"] for s in coverage["unassigned_stakeholders"]] == people[2:]
    assert coverage["unassigned_proportion"] == 0.5


@pytest.mark.asyncio
async def test_several_stakeholders_on_one_activity_is_never_a_mismatch(project):
    """The ordinary shape of frontline work. Three people on one of two activities, and both
    activities covered, must leave both proportions at zero and raise nothing."""
    _write_registry(project["projects_dir"], _nodes(2))
    people = await _people(project["id"], 4)
    await _assign(project["id"], [
        (people[0], "1.1"), (people[1], "1.1"), (people[2], "1.1"), (people[3], "1.2"),
    ])

    coverage = await _coverage(project["id"])

    assert coverage["uncovered_proportion"] == 0.0
    assert coverage["unassigned_proportion"] == 0.0
    assert coverage["uncovered_beyond_threshold"] is False
    assert coverage["unassigned_beyond_threshold"] is False
    assert await _report_issues(project["id"]) == []


@pytest.mark.asyncio
async def test_a_seeded_stakeholder_counts_in_the_roster(project):
    """`is_synthetic` marks a row as seeded, not as absent. Sixty of them are live on
    sp-gs-am, the Interview Coordinator plans sessions from them, and a roster figure that
    ignored them would describe an engagement nobody is running."""
    _write_registry(project["projects_dir"], _nodes(2))
    people = await _people(project["id"], 4, synthetic=2)
    await _assign(project["id"], [(people[0], "1.1"), (people[1], "1.2")])

    coverage = await _coverage(project["id"])

    async with get_connection(SLUG) as conn:
        async with conn.execute("SELECT COUNT(*) FROM stakeholders WHERE is_synthetic=1") as cur:
            seeded = (await cur.fetchone())[0]
    assert seeded == 2, "fixture must actually mark two rows as seeded"
    assert coverage["roster_total"] == 4
    assert coverage["stakeholders_unassigned"] == 2
    assert coverage["unassigned_proportion"] == 0.5


@pytest.mark.asyncio
async def test_before_the_value_chain_exists_nothing_is_uncovered(project):
    """No registry means no activities to cover. Reporting a project as wholly uncovered
    before the mapper has run would raise an issue against work nobody could have done."""
    await _people(project["id"], 3)

    coverage = await _coverage(project["id"])

    assert coverage["activities_total"] == 0
    assert coverage["uncovered_proportion"] == 0.0
    assert coverage["uncovered_beyond_threshold"] is False
    assert [i["title"] for i in await _report_issues(project["id"])] == [
        "3 of 3 stakeholders are assigned to no activity (100.0%)"
    ], "the roster direction still answers - only the activity one is unanswerable"


# ── Each direction alone, and neither masking the other ───────────────────────


@pytest.mark.asyncio
async def test_uncovered_activities_raise_while_a_fully_placed_roster_does_not(project):
    """Two of ten activities have nobody - 20%, past the threshold - and every one of the
    five people is placed. Exactly one issue, and it is the activity one."""
    _write_registry(project["projects_dir"], _nodes(10))
    people = await _people(project["id"], 5)
    await _assign(project["id"], [
        (people[0], "1.1"), (people[1], "1.2"), (people[2], "1.3"),
        (people[3], "1.4"), (people[4], "1.5"),
        (people[0], "1.6"), (people[1], "1.7"), (people[2], "1.8"),
    ])

    coverage = await _coverage(project["id"])
    assert coverage["uncovered_beyond_threshold"] is True
    assert coverage["unassigned_beyond_threshold"] is False
    assert coverage["unassigned_proportion"] == 0.0

    issues = await _report_issues(project["id"])
    assert len(issues) == 1, [i["title"] for i in issues]
    assert issues[0]["title"] == "2 of 10 activities have no stakeholder assigned (20.0%)"
    assert "1.9" not in issues[0]["title"]


@pytest.mark.asyncio
async def test_an_idle_roster_raises_while_a_fully_covered_chain_does_not(project):
    """Every activity has somebody and two of five people have nothing - 40%. The opposite
    issue, alone. A single combined check would have let this arrive as the one above."""
    _write_registry(project["projects_dir"], _nodes(2))
    people = await _people(project["id"], 5)
    await _assign(project["id"], [
        (people[0], "1.1"), (people[1], "1.1"), (people[2], "1.2"),
    ])

    coverage = await _coverage(project["id"])
    assert coverage["unassigned_beyond_threshold"] is True
    assert coverage["uncovered_beyond_threshold"] is False
    assert coverage["uncovered_proportion"] == 0.0

    issues = await _report_issues(project["id"])
    assert len(issues) == 1, [i["title"] for i in issues]
    assert issues[0]["title"] == "2 of 5 stakeholders are assigned to no activity (40.0%)"


@pytest.mark.asyncio
async def test_both_directions_can_be_past_the_threshold_at_once(project):
    """Two issues, not one. They call for opposite work - find more people, or give the
    people you have something to speak about - so they must be separately readable."""
    _write_registry(project["projects_dir"], _nodes(10))
    people = await _people(project["id"], 5)
    await _assign(project["id"], [(people[0], "1.1"), (people[1], "1.2")])

    issues = await _report_issues(project["id"])

    assert sorted(i["title"] for i in issues) == [
        "3 of 5 stakeholders are assigned to no activity (60.0%)",
        "8 of 10 activities have no stakeholder assigned (80.0%)",
    ]


@pytest.mark.asyncio
async def test_exactly_the_threshold_is_not_past_it(project):
    """"More than a 10% mismatch" - so a tenth exactly is reported as no issue, in both
    directions. Ten activities with one gap and ten people with one unplaced."""
    assert COVERAGE_MISMATCH_THRESHOLD == 0.10
    _write_registry(project["projects_dir"], _nodes(10))
    people = await _people(project["id"], 10)
    await _assign(project["id"], [
        (person, f"1.{n + 1}") for n, person in enumerate(people[:9])
    ])

    coverage = await _coverage(project["id"])

    assert coverage["uncovered_proportion"] == 0.1
    assert coverage["unassigned_proportion"] == 0.1
    assert coverage["uncovered_beyond_threshold"] is False
    assert coverage["unassigned_beyond_threshold"] is False
    assert await _report_issues(project["id"]) == []


# ── What Pamela publishes ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pamela_reports_the_numbers_rather_than_a_verdict(project):
    """The count and the denominator are the content. Both appear in the title, the block on
    the report carries the same figures, and the mapping itself does not - eighty names belong
    in Jordan's engagement plan, not in a project health report."""
    from api.services.pam_report_service import build_pam_report

    _write_registry(project["projects_dir"], _nodes(4))
    people = await _people(project["id"], 3)
    await _assign(project["id"], [(people[0], "1.1")])

    report = await build_pam_report(SLUG)
    block = report["assignment_coverage"]

    assert block["activities_total"] == 4
    assert block["activities_uncovered"] == 3
    assert block["roster_total"] == 3
    assert block["stakeholders_unassigned"] == 2
    assert block["threshold"] == COVERAGE_MISMATCH_THRESHOLD
    assert "assignments" not in block

    issues = [i for i in report["issues"] if i["crew"] == "stakeholder_management"]
    assert {i["severity"] for i in issues} == {"medium"}
    for issue in issues:
        assert "75.0%" in issue["description"] or "66.7%" in issue["description"]


@pytest.mark.asyncio
async def test_a_coverage_issue_denies_the_report_its_no_issues_answer(project):
    """A medium issue sits in neither the critical nor the high count, so without the `issues`
    clause on the amber branch the report says "No issues or risks identified" while carrying
    one.

    The fixture has to raise **no risk at all** for that to be the property under test, and
    every risk has its own trigger: fewer than three documents, fewer than five stakeholders,
    milestones with no dates. A project carrying any of them goes amber for that reason and the
    assertion below passes whatever the branch does - which it did, until this test was made to
    earn its failure.
    """
    from api.services.pam_report_service import build_pam_report

    _write_registry(project["projects_dir"], _nodes(10))
    people = await _people(project["id"], 5)
    await _assign(project["id"], [(people[n], f"1.{n + 1}") for n in range(5)])
    async with get_connection(SLUG) as conn:
        for n in range(3):
            await conn.execute(
                "INSERT INTO client_documents"
                " (project_id, filename, original_name, file_path) VALUES (?,?,?,?)",
                (project["id"], f"doc{n}.pdf", f"Doc {n}.pdf", f"/tmp/doc{n}.pdf"),
            )
        await conn.commit()

    report = await build_pam_report(SLUG)

    assert report["risks"] == [], "the fixture must raise no risk, or this proves nothing"
    assert report["pending_reviews"] == 0
    assert [i["crew"] for i in report["issues"]] == ["stakeholder_management"]
    assert report["overall_health"] == "amber"
    assert "No issues or risks identified" not in report["health_summary"]


# ── Reaching the agent: the loop this slice exists to close ───────────────────


async def _task_description(project_id: int) -> str:
    """The description the Stakeholder Manager is actually handed by the dispatch path.

    Not the factory called directly, and not the coverage helper: the property is that the
    mapping travels from the table into his prompt, and the only place that holds is here.
    The real factory is called - with a stubbed LLM and no tools - so the formatting under
    test is the production one.
    """
    from agents.crews.stakeholder_management_crew import create_stakeholder_management_crew

    async with get_connection(SLUG) as conn:
        crew_run_id = await insert_crew_run(
            conn, project_id=project_id, crew_name="stakeholder_management", status="running",
        )

    built: dict = {}

    def _spy(**kwargs):
        with patch(
            "agents.crews.stakeholder_management_crew.get_tools_for_agent", return_value=[]
        ):
            built["crew"] = create_stakeholder_management_crew(
                **kwargs, llm=MagicMock(spec=LLM)
            )
        stub = MagicMock()
        stub.tasks = built["crew"].tasks
        stub.kickoff_async = AsyncMock(return_value="done")
        return stub

    with patch(
        "api.services.run_service.load_project_config",
        return_value={"sector": "rail", "public_url": "https://example.test"},
    ), patch(
        "agents.crews.stakeholder_management_crew.create_stakeholder_management_crew",
        side_effect=_spy,
    ):
        from api.services.run_service import build_and_run_crew
        await build_and_run_crew(SLUG, "stakeholder_management", crew_run_id)

    return built["crew"].tasks[0].description


@pytest.mark.asyncio
async def test_the_dispatch_path_hands_him_the_mapping(project):
    """He could not read it. `SQLiteStateTool` resolves a key through `agent_outputs`, so the
    read returned "Error: no state found" and the agent whose task is to find the gaps in the
    mapping had never seen the mapping."""
    _write_registry(project["projects_dir"], [
        {"id": "1.1", "label": "Order Fulfilment", "level": "L2", "active": True},
        {"id": "1.2", "label": "Billing", "level": "L2", "active": True},
    ])
    async with get_connection(SLUG) as conn:
        alice = await insert_stakeholder(
            conn, project_id=project["id"], name="Alice Chen", job_title="Head of Ops"
        )
        bob = await insert_stakeholder(
            conn, project_id=project["id"], name="Bob Smith", job_title="Packer"
        )
    await _assign(project["id"], [(alice, "1.1"), (bob, "1.1")])

    description = await _task_description(project["id"])

    assert "Alice Chen" in description
    assert "Head of Ops" in description
    assert "Bob Smith" in description
    assert "Order Fulfilment" in description
    assert f"[id:{alice}]" in description
    assert "1.2" in description, "the activity nobody speaks for must be named too"


@pytest.mark.asyncio
async def test_the_dispatch_path_hands_him_both_proportions(project):
    """Given to him computed. A model asked to divide 2 by 10 in prose is a model whose answer
    can differ from the one Pamela raises against the same rows."""
    _write_registry(project["projects_dir"], _nodes(10))
    people = await _people(project["id"], 5)
    await _assign(project["id"], [(people[n], f"1.{n + 1}") for n in range(4)])

    description = await _task_description(project["id"])

    assert "6 of 10 active value chain activities (60.0%)" in description
    assert "1 of 5 on the roster (20.0%)" in description


@pytest.mark.asyncio
async def test_he_is_no_longer_sent_to_the_state_tool_for_the_table(project):
    """The instruction that was never once served, removed rather than left to fail quietly."""
    _write_registry(project["projects_dir"], _nodes(2))
    people = await _people(project["id"], 1)
    await _assign(project["id"], [(people[0], "1.1")])

    description = await _task_description(project["id"])

    assert "key='stakeholder_assignments'" not in description
    assert "SQLiteStateTool cannot read it" in description


@pytest.mark.asyncio
async def test_an_absent_mapping_is_declared_absent_rather_than_reported_as_none(project):
    """A run given no coverage block must not let him report zero assignments as fact.

    `build_and_run_agent` - the standalone dispatch - fetches nothing on an agent's behalf, so
    this case is reachable today.
    """
    from agents.crews.stakeholder_management_crew import create_stakeholder_management_crew

    with patch(
        "agents.crews.stakeholder_management_crew.get_tools_for_agent", return_value=[]
    ):
        crew = create_stakeholder_management_crew(
            slug=SLUG, run_id=1, sector="rail", llm=MagicMock(spec=LLM)
        )

    description = crew.tasks[0].description
    # The block's own first sentence, not its heading - step 2 names the heading in prose.
    assert "This mapping is a durable project fact" not in description
    assert "COVERAGE, ALREADY COMPUTED" not in description
    assert "treat the assignments as unknown rather than as empty" in description


@pytest.mark.asyncio
async def test_an_empty_mapping_is_shown_as_empty_rather_than_omitted(project):
    """Nobody assigned to anything is a finding, and the strongest one this report can carry."""
    _write_registry(project["projects_dir"], _nodes(2))
    await _people(project["id"], 2)

    description = await _task_description(project["id"])

    assert "(nobody is assigned to any activity)" in description
    assert "2 of 2 active value chain activities (100.0%)" in description


# ── The graph says what is true, and no more ──────────────────────────────────


def test_the_declaration_says_the_mapping_now_reaches_him():
    """`agents/reads.py` recorded this as unresolvable. It is a real read now, by the dispatch
    path - and the guard next door refuses a source that sits in both lists, so this cannot be
    satisfied by adding one without removing the other."""
    from agents.reads import AGENT_READS, UNRESOLVABLE_READS, VIA_DISPATCH

    declared = {r.source: r for r in AGENT_READS["stakeholder_manager"]}
    assert "stakeholder_assignments" in declared
    assert declared["stakeholder_assignments"].via == VIA_DISPATCH
    assert "stakeholder_assignments" not in {
        u.source for u in UNRESOLVABLE_READS if u.agent_id == "stakeholder_manager"
    }


def test_the_edge_into_the_interviews_still_carries_nothing():
    """Two crews reading one table from the dispatch path is not one handing over to the other.

    Jordan can read the mapping now and still writes nothing the interviews read, so the arrow
    stays sequencing. Asserted here as well as in the edge tests because this slice is exactly
    when somebody would be tempted to relabel it.
    """
    from agents.graph import EdgeKind, build_graph

    edge = next(
        e for e in build_graph().edges
        if (e.source, e.target) == ("stakeholder_management", "discovery_interviews")
    )
    assert edge.kind is EdgeKind.SEQUENCING
    assert edge.artefacts == ()


# ── The interview process is not his ──────────────────────────────────────────
#
# Jordan's brief was written too broad before the pipeline had been run end to end, and the
# breadth produced a live defect: a drafting step told him to emit `{url_base}/{session_token}`
# when he has no route to any session token. The lint that removed it left nothing behind that
# would notice its return - putting `InterviewSessionTool` back in his tool list passed the whole
# suite - so the absence is asserted at the two boundaries rather than described in a commit
# message. Both drive the real doors: the registry the crew factory calls, and the task
# description the agent is actually handed.


def test_jordan_does_not_hold_the_interview_session_tool():
    """A tool an agent holds is a tool it can decide to call.

    Asserted against `get_tools_for_agent` rather than against `tool_map`'s source, because the
    registry is what `create_stakeholder_management_crew` calls. The positive control is in the
    same assertion: he must still hold `SQLiteStateTool`, or a registry that raised or returned
    nothing would satisfy the absence for the wrong reason.
    """
    from agents.tools.registry import get_tools_for_agent

    held = {
        type(tool).__name__
        for tool in get_tools_for_agent(
            "stakeholder_manager", slug=SLUG, run_id=1, sector="rail"
        )
    }
    assert held == {"SQLiteStateTool"}, held


@pytest.mark.asyncio
async def test_his_task_asks_for_nothing_about_the_interview_process(project):
    """Every removed instruction, named individually, plus the sentence that replaced them.

    The absences are the removed *instructions* and the removed *schema keys*, not the word
    "interview" - the task still names the interview process once, to say it is the Interview
    Coordinator's. A bare "interview" not in description would fail on that sentence, and
    deleting the sentence to satisfy it would remove the only thing telling him whose the
    process is.
    """
    description = await _task_description(project["id"])

    for gone in (
        "key='interview_sessions'",   # the session-state read
        "not yet invited",            # nodes with no sessions created
        "needs chasing",              # pending over five days
        "needs re-engagement",        # abandoned
        "may need more perspectives", # single-completer
        "draft an appropriate message",
        "draft_message",
        "outreach_actions",
        "re_engage",
        "stakeholders_pending",
        "stakeholders_completed",
    ):
        assert gone not in description, f"still asks for {gone!r}"

    assert "do not draft any message to a stakeholder" in description
    # The positive control: the half of the task that stays must still be there, or a task
    # that failed to build would pass every absence above.
    assert "key='value_chain_registry'" in description
    assert "key='stakeholder_engagement_plan'" in description
    assert "assignment_coverage" in description
