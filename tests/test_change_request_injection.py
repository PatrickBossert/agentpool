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

@pytest.fixture(autouse=True)
def _granted_authority():
    """This module is about what reaches the agent's task, not about who may post a
    review. The client fixture's sysadmin token names no real user, so caller_may_contribute
    correctly answers False for it and both review doors would 403 before recording anything.

    Not a weakening of the gate: tests/test_write_door_authority.py drives every one of
    these doors over HTTP as a real member with and without the flag, so deleting the gate
    fails there. Patched on the router module, where the name is looked up - the routers
    bind their own reference via `from ... import`, so patching authority_service itself
    would miss them (CLAUDE.md's four-crew-tests entry).
    """
    with patch("api.routers.reviews.caller_may_contribute", new=AsyncMock(return_value=True)):
        yield




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
async def test_a_request_against_a_superseded_output_is_still_gathered(project):
    """Scoped by output_type, not by output_id - inverted from this test's old name and
    assertions, which encoded the opposite as desired.

    The old scoping matched only output ids that were still `is_current`, so a request
    raised against v1 became permanently unreachable the moment v2 became current - the
    "born orphaned" case from the design review: the crew moves on before a still-open
    review naming the old version gets resolved, and the resolution's notes then have
    nowhere left to land. Gathering by output_type instead means the request rides along
    with the artefact (value_chain_model) rather than the specific row, as long as this
    crew's own agents still hold the type's current version - which they do here. Do not
    restore the old `text == "" / ids == []` assertions; that was the bug, not a guarantee.
    """
    from api.services.run_service import _fetch_change_requests

    async with get_connection(SLUG) as conn:
        old = await _output(conn, is_current=0, version=1)
        await _output(conn, is_current=1, version=2)
        await insert_output_change(
            conn, output_id=old, requested_by="alice", source="review",
            request="an old request", summary="", kind="change_request",
        )

    text, ids = await _fetch_change_requests(SLUG, "discovery_mapping")

    assert "an old request" in text
    assert len(ids) == 1


async def _excel_output(conn, *, agent_name, is_current=1, version=1):
    """An 'excel' output - the one output_type two different crews' agents both write
    (Portfolio Manager in value_design, the Business Plan Generator in business_plan),
    used to prove the output_type widening in _fetch_change_requests cannot leak a
    request from one crew to the other.
    """
    cur = await conn.execute(
        "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
        " version, is_current, review_status)"
        " VALUES (1,?,'excel',?,?,?,'pending')",
        (agent_name, f"e_v{version}.json", version, is_current),
    )
    await conn.commit()
    return cur.lastrowid


@pytest.mark.asyncio
async def test_a_shared_output_type_does_not_leak_between_crews(project):
    """output_type is not unique to one crew - guard against the regression that widening
    the scope from output_id to output_type would most plausibly introduce.

    Portfolio Manager's (value_design) old 'excel' export is superseded by the Business
    Plan Generator's (business_plan) 'excel' export, which is now current - so business_plan
    genuinely owns the type "excel" in the widened sense (one of its own agents holds the
    current row). A change request against Portfolio Manager's superseded row must not be
    handed to business_plan: matching on output_type alone would find it, since 'excel' is
    among business_plan's owned types too. Only the per-row agent_name check - kept
    unconditionally, not just when types happen not to collide - excludes it, because that
    specific row was never produced by one of business_plan's own agents.
    """
    from api.services.run_service import _fetch_change_requests

    async with get_connection(SLUG) as conn:
        portfolio_excel = await _excel_output(conn, agent_name="portfolio_manager", is_current=0, version=1)
        await _excel_output(conn, agent_name="business_plan_generator", is_current=1, version=2)
        await insert_output_change(
            conn, output_id=portfolio_excel, requested_by="alice", source="review",
            request="tidy the portfolio excel", summary="", kind="change_request",
        )

    bp_text, bp_ids = await _fetch_change_requests(SLUG, "business_plan")

    assert bp_text == ""
    assert bp_ids == []


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


async def _requirements_output_of_type(conn, *, agent_name, output_type, version=1, is_current=1):
    """A current output for one of the requirements crew's own agents, with a caller-chosen
    output_type - used to give the crew several distinct current outputs at once, the way a
    real project accumulates them, so a fan-out across all of them can be simulated."""
    cur = await conn.execute(
        "INSERT INTO agent_outputs (project_id, agent_name, output_type, file_path,"
        " version, is_current, review_status)"
        " VALUES (1,?,?,?,?,?,'pending')",
        (agent_name, output_type, f"{output_type}_v{version}.json", version, is_current),
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


# ── Both feedback doors, exactly once ───────────────────────────────────────────────────
#
# api/routers/reviews.py has two doors that can record decision='changes_requested' with
# notes: POST /projects/{slug}/review (submit_review - used by RerunDialog's "Suggest a
# revision" and AgentStatusTab's inline "Revise") and PATCH /projects/{slug}/reviews/{id}
# (resolve_hitl_review - used by ReviewDialog, the pending-review queue). Before this fix,
# only the PATCH door wrote an output_changes row; run_service._fetch_revision_notes read
# human_reviews.notes directly and injected a REVISION INSTRUCTIONS block for *both* doors,
# which meant the PATCH door's note reached the agent twice and the POST door's note reached
# it only through that one now-removed path. Both doors now write output_changes, and
# _fetch_change_requests is the only path a reviewer's note travels by, for either door.
#
# These use the real router functions (not just _fetch_change_requests) and the `client`
# fixture from conftest.py, so the assertion covers the whole path: HTTP request in,
# task.description at kickoff out.

DOOR_PROJECT_TEMPLATE = {
    "llm_mode": "standard", "sector": "utilities",
    "stakeholder_groups": [], "value_stream_labels": [], "review_gates": True, "slack_channel": "",
}


async def _seed_door_project(client, slug: str) -> int:
    """A project with one current output owned by the requirements crew's own agent."""
    await client.post("/projects", json={**DOOR_PROJECT_TEMPLATE, "client_slug": slug})
    from api.database import get_connection, fetch_project, insert_agent_output

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        output_id = await insert_agent_output(
            conn,
            project_id=project["id"],
            agent_name="requirements_analyst",
            output_type="requirements_doc",
            file_path="/tmp/door_req.json",
            version=1,
        )
    return output_id


async def _run_requirements_crew_and_capture_description(slug: str) -> str:
    """Build and run the requirements crew with a mocked crew factory, capturing the task
    description crewai would actually have seen at kickoff - the same boundary
    test_change_request_text_reaches_the_task_before_kickoff patches above."""
    mock_task = MagicMock()
    mock_task.description = "original task body"
    mock_crew = MagicMock()
    mock_crew.tasks = [mock_task]
    seen: list[str] = []

    async def _fake_kickoff():
        seen.append(mock_task.description)
        return "done"

    mock_crew.kickoff_async = AsyncMock(side_effect=_fake_kickoff)

    import agents.crews.requirements_crew  # noqa: F401  ensure importable before patching
    with patch(
        "agents.crews.requirements_crew.create_requirements_crew",
        return_value=mock_crew,
    ):
        from api.services.run_service import build_and_run_crew
        await build_and_run_crew(slug, "requirements", run_id=1)

    return seen[0]


@pytest.mark.asyncio
async def test_the_post_review_door_reaches_the_agent_exactly_once(client):
    """RerunDialog's 'Suggest a revision' and AgentStatusTab's inline 'Revise' both submit
    through POST /review. Before this fix that endpoint never wrote output_changes, so its
    only delivery mechanism was the REVISION INSTRUCTIONS injection this branch retires -
    wiring this door to output_changes is what makes retiring that injection safe rather
    than a silent regression for these two flows.
    """
    slug = "door-post-test"
    output_id = await _seed_door_project(client, slug)

    resp = await client.post(
        f"/projects/{slug}/review",
        json={"output_id": output_id, "decision": "changes_requested",
              "notes": "use the approved 2025 figures"},
    )
    assert resp.status_code == 201

    description = await _run_requirements_crew_and_capture_description(slug)

    assert description.count("use the approved 2025 figures") == 1
    assert "REQUESTED CHANGES" in description
    assert "REVISION INSTRUCTIONS" not in description


@pytest.mark.asyncio
async def test_the_patch_review_door_reaches_the_agent_exactly_once(client):
    """ReviewDialog's pending-review queue submits through PATCH /reviews/{id}. This door
    already wrote output_changes before this fix; what this fix closes is that
    human_reviews.notes was *also* being injected as REVISION INSTRUCTIONS, so the same
    note reached the agent twice.
    """
    slug = "door-patch-test"
    output_id = await _seed_door_project(client, slug)
    from api.database import get_connection

    async with get_connection(slug) as conn:
        cur = await conn.execute(
            "INSERT INTO human_reviews (output_id, decision) VALUES (?, 'pending')",
            (output_id,),
        )
        review_id = cur.lastrowid
        await conn.commit()

    resp = await client.patch(
        f"/projects/{slug}/reviews/{review_id}",
        json={"decision": "changes_requested", "notes": "use the approved 2025 figures"},
    )
    assert resp.status_code == 200

    description = await _run_requirements_crew_and_capture_description(slug)

    assert description.count("use the approved 2025 figures") == 1
    assert "REQUESTED CHANGES" in description
    assert "REVISION INSTRUCTIONS" not in description


@pytest.mark.asyncio
async def test_the_same_note_fanned_out_across_a_crews_outputs_reaches_the_agent_once(client, crew_project):
    """RerunDialog's "Suggest a revision" posts the same note once per output shown for the
    crew (`outputs.map(o => projectsApi.review(...))` in RerunDialog.tsx) - one POST per
    output, each writing its own output_changes row with identical request text. Before
    deduplicating at assembly, _fetch_change_requests rendered one bullet per row: the same
    sentence three times here, roughly nine for a crew the size of discovery_interviews -
    the same defect class this wave exists to remove, reintroduced by fan-out instead of by
    double injection.

    Both halves of the fix are asserted: the injected text carries the note once, and all
    three rows still end up applied. Deduplicating change_ids itself (rather than only the
    rendered text) would pass the first half while leaving two rows open forever - the
    failure the open/applied lifecycle exists to prevent.
    """
    async with get_connection(CREW_SLUG) as conn:
        a = await _requirements_output_of_type(
            conn, agent_name="requirements_analyst", output_type="requirements_doc"
        )
        b = await _requirements_output_of_type(
            conn, agent_name="requirements_analyst", output_type="requirements_analysis"
        )
        c = await _requirements_output_of_type(
            conn, agent_name="requirements_capture", output_type="captured_requirements"
        )

    note = "use the approved 2025 figures"
    for output_id in (a, b, c):
        resp = await client.post(
            f"/projects/{CREW_SLUG}/review",
            json={"output_id": output_id, "decision": "changes_requested", "notes": note},
        )
        assert resp.status_code == 201

    description = await _run_requirements_crew_and_capture_description(CREW_SLUG)

    assert description.count(note) == 1
    assert "REQUESTED CHANGES" in description

    for output_id in (a, b, c):
        row = await _change_status(output_id)
        assert row["status"] == "applied"
