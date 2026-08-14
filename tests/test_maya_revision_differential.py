# tests/test_maya_revision_differential.py
"""A script sent back to Maya must reach the task she actually receives.

Step 4 of her prompt says: generate only nodes with no script yet. A reviewer can now send
an individual script back for revision (script_review_service.record_script_review with
return_to='agent') - but a sent-back script *has* a script, so without an explicit
exception she skips it. The revision request would arrive beside an instruction to ignore
it, and nothing would happen.

Mirrors tests/test_change_request_injection.py's
test_change_request_text_reaches_the_task_before_kickoff and
tests/test_validation_warning_injection.py's
test_the_task_description_maya_receives_contains_the_coverage_warning: the crew factory and
crewai's Crew/Task are mocked at the same boundary those tests use (patching the
crew-creation function, and Crew.tasks / kickoff_async on the returned mock), because a real
crewai.Crew is never actually built here - patching crewai.Crew.kickoff_async directly, as
an earlier draft of this test did, only works if create_assessment_design_crew returns a
real crewai.Crew instance, and this codebase's own convention for this exact boundary
(established in the two files above) mocks the factory return value instead.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import yaml

from api.database import get_connection, fetch_project, insert_project
from api.config import get_settings

SLUG = "maya-revision-test"


@pytest_asyncio.fixture
async def assessment_project(tmp_path, monkeypatch):
    """A project with a config.yaml, so build_and_run_crew's own config load succeeds -
    the assessment_design branch needs it. Mirrors assessment_project in
    tests/test_validation_warning_injection.py."""
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    projects_dir = tmp_path / "projects"
    monkeypatch.setenv("PROJECTS_DIR", str(projects_dir))
    project_dir = projects_dir / SLUG
    project_dir.mkdir(parents=True)
    (project_dir / "config.yaml").write_text(
        yaml.dump({"llm_mode": "standard", "sector": "utilities"})
    )
    async with get_connection(SLUG) as conn:
        await insert_project(
            conn, slug=SLUG, llm_mode="standard", sector="utilities", config_json="{}"
        )
    yield SLUG
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_a_script_sent_back_to_the_agent_reaches_the_task_maya_receives(
    assessment_project,
):
    """Asserted on the description the task actually carries, not on the ledger row. The
    row is the mechanism; the prompt is the property. Without this clause a revision
    request arrives beside an instruction to skip every node that already has a script,
    and she ignores it."""
    slug = assessment_project

    mock_task = MagicMock()
    mock_task.description = "original task body"
    mock_crew = MagicMock()
    mock_crew.tasks = [mock_task]
    seen_at_kickoff: list[str] = []

    async def _fake_kickoff():
        seen_at_kickoff.append(mock_task.description)
        return "ok"

    mock_crew.kickoff_async = AsyncMock(side_effect=_fake_kickoff)

    import agents.crews.assessment_design_crew  # noqa: F401  ensure importable before patching
    with patch(
        "agents.crews.assessment_design_crew.create_assessment_design_crew",
        return_value=mock_crew,
    ), patch(
        "api.services.script_review_service.scripts_awaiting_regeneration",
        new=AsyncMock(return_value=[
            {"script_id": "SC-042", "node_id": "3.3.2", "node_label": "Billing",
             "notes": "the maturity anchors are wrong"}]),
    ):
        from api.services.run_service import build_and_run_crew
        result = await build_and_run_crew(slug, "assessment_design", run_id=7)

    assert result == "ok"
    assert len(seen_at_kickoff) == 1
    assert "SC-042" in seen_at_kickoff[0]
    assert "the maturity anchors are wrong" in seen_at_kickoff[0]
    # The injection must prepend, not replace - a regression that swapped the description
    # instead of prefixing it would still satisfy the assertions above.
    assert seen_at_kickoff[0].endswith("\n\noriginal task body")


def _minimal_script(script_id, node_id, label):
    """The smallest body validate_scripts (api/services/interview_script_model.py) accepts -
    matches the working shape in tests/test_script_ledger_registration.py."""
    return {
        "script_id": script_id, "node_id": node_id, "node_label": label,
        "level": "L2", "relationship": "internal", "sections": [],
    }


async def _run_assessment_design_and_capture(slug, run_id):
    """Drive one real build_and_run_crew call for assessment_design, mocking only the
    crew factory and Crew.tasks/kickoff_async (this file's established boundary - see the
    module docstring), and return the description Maya's task actually carried at
    kickoff."""
    mock_task = MagicMock()
    mock_task.description = "original task body"
    mock_crew = MagicMock()
    mock_crew.tasks = [mock_task]
    seen: list[str] = []

    async def _fake_kickoff():
        seen.append(mock_task.description)
        return "ok"

    mock_crew.kickoff_async = AsyncMock(side_effect=_fake_kickoff)

    import agents.crews.assessment_design_crew  # noqa: F401
    with patch(
        "agents.crews.assessment_design_crew.create_assessment_design_crew",
        return_value=mock_crew,
    ):
        from api.services.run_service import build_and_run_crew
        await build_and_run_crew(slug, "assessment_design", run_id=run_id)
    return seen[0]


@pytest.mark.asyncio
async def test_a_regenerated_script_stops_being_injected_on_the_next_run(assessment_project):
    """Code review round 1, Important 1: without a version filter, a send-back never
    clears, and Maya regenerates the same script on every future run forever - rewriting
    text a consultant may have edited to address the very note that sent it back, which is
    precisely the harm step 4's differential exists to prevent.

    Driven through a real interview_scripts write (via SQLiteStateTool, the same path
    register_scripts_sync reaches in production), a real record_script_review, and two real
    build_and_run_crew calls with a real interview_scripts write in between them -
    asserting on the description each run actually hands to Maya, never on
    scripts_awaiting_regeneration's return value or on last_version directly.
    """
    from agents.tools.sqlite_state import SQLiteStateTool

    slug = assessment_project
    tool = SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=1)

    out = tool._run(
        operation="write", key="interview_scripts", agent_name="interaction_designer",
        value=json.dumps({"SC-042": _minimal_script("SC-042", "3.3.2", "Billing")}),
    )
    assert out.startswith("Written to"), out

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        cur = await conn.execute(
            "SELECT last_version FROM interview_script_ledger WHERE script_id=?",
            ("SC-042",),
        )
        row = await cur.fetchone()
        current_version = row[0]

        from api.services.script_review_service import record_script_review
        await record_script_review(
            conn, project_id=project["id"], script_id="SC-042", reviewer="bo",
            decision="changes_requested", notes="the maturity anchors are wrong",
            at_version=current_version, return_to="agent",
        )

    run_1 = await _run_assessment_design_and_capture(slug, 101)
    run_1_injected = "SC-042" in run_1
    assert run_1_injected, "RUN 1 must inject the send-back before any regeneration"

    # Regenerate SC-042 through a real interview_scripts write, exactly as Maya would after
    # reading the injected block - register_scripts_sync bumps last_version because this
    # batch names SC-042 again.
    out2 = tool._run(
        operation="write", key="interview_scripts", agent_name="interaction_designer",
        value=json.dumps({"SC-042": _minimal_script("SC-042", "3.3.2", "Billing")}),
    )
    assert out2.startswith("Written to"), out2

    run_2 = await _run_assessment_design_and_capture(slug, 102)
    run_2_injected = "SC-042" in run_2
    assert not run_2_injected, (
        "RUN 2 must NOT re-inject SC-042 - last_version has moved past reviewed_at_version, "
        "so the note has been addressed"
    )


@pytest.mark.asyncio
async def test_a_backfilled_script_with_no_recorded_version_injects_on_its_first_send_back(
    assessment_project,
):
    """Code review round 2: the nullable column scripts_awaiting_regeneration must guard is
    last_version, not reviewed_at_version. interview_script_ledger.last_version has no
    default, and script_ledger_backfill.py deliberately omits it when loading a legacy JSON
    registry - those ids predate per-batch versioning and simply never had one. SQL's
    NULL <= 0 evaluates to NULL, not true, so a naive guard on reviewed_at_version alone let
    a backfilled row disappear from the WHERE clause the moment it was sent back: the
    send-back was recorded, visible on the ledger endpoint, and notified, but never reached
    Maya - not on this run, and not ever, since once she does write something last_version
    becomes >= 1, permanently greater than reviewed_at_version=0.

    Driven through the real backfill_script_ledger, not a hand-inserted row: every ledger
    row this file's other tests build goes through SQLiteStateTool/register_scripts_sync,
    which always stamps a version, so none of them can produce the row shape a real backfill
    does. Asserted on the description build_and_run_crew's first real run actually hands to
    Maya, matching this file's other tests.
    """
    from api.services.script_ledger_backfill import backfill_script_ledger
    from api.services.script_review_service import record_script_review

    slug = assessment_project
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        inserted = await backfill_script_ledger(
            conn, project_id=project["id"],
            registry={"scripts": [
                {"id": "SC-777", "node_id": "4.1", "node_label": "Legacy Onboarding",
                 "active": True},
            ]},
        )
        assert inserted == 1

        cur = await conn.execute(
            "SELECT last_version FROM interview_script_ledger WHERE script_id=?",
            ("SC-777",),
        )
        row = await cur.fetchone()
        assert row["last_version"] is None, (
            "precondition: a real backfill leaves last_version unset - the row shape this "
            "test exists to cover"
        )

        # Mirrors api/routers/script_reviews.py's own at_version derivation exactly:
        # at_version=row["last_version"] or 0.
        await record_script_review(
            conn, project_id=project["id"], script_id="SC-777", reviewer="bo",
            decision="changes_requested", notes="check the maturity anchors on this one too",
            at_version=row["last_version"] or 0, return_to="agent",
        )

    run_1 = await _run_assessment_design_and_capture(slug, 201)
    assert "SC-777" in run_1, (
        "a backfilled script with no recorded version must still inject on its first "
        "send-back"
    )
    assert "check the maturity anchors on this one too" in run_1


@pytest.mark.asyncio
async def test_a_regenerated_script_returns_to_pending_on_the_ledger_row(assessment_project):
    """Final review, Important 5: review_status never came back from changes_requested.

    After Maya regenerates, the QUERY clears correctly - scripts_awaiting_regeneration
    stops returning the row, which the test above already proves. The ROW did not: it still
    read review_status='changes_requested', review_return_to='agent', with last_version
    ahead of reviewed_at_version. The row is what the review UI renders, so every
    regenerated script showed "Sent back" forever, beside a "changed since" chip. The
    design promises derived state on the ledger row; the derived state was stale.

    SC-099 is the control, and it is deliberately an *approved* script rather than an
    untouched one: a blanket reset in register_scripts_sync would be invisible against a
    row that was already pending.
    """
    from agents.tools.sqlite_state import SQLiteStateTool
    from api.services.script_review_service import record_script_review

    slug = assessment_project
    tool = SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=1)

    out = tool._run(
        operation="write", key="interview_scripts", agent_name="interaction_designer",
        value=json.dumps({"SC-042": _minimal_script("SC-042", "3.3.2", "Billing"),
                          "SC-099": _minimal_script("SC-099", "3.3.3", "Metering")}),
    )
    assert out.startswith("Written to"), out

    async def _row(script_id):
        async with get_connection(slug) as conn:
            conn.row_factory = None
            cur = await conn.execute(
                "SELECT review_status, review_return_to, last_version, reviewed_at_version"
                "  FROM interview_script_ledger WHERE script_id=?",
                (script_id,),
            )
            return await cur.fetchone()

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        version = (await _row("SC-042"))[2]
        await record_script_review(
            conn, project_id=project["id"], script_id="SC-042", reviewer="bo",
            decision="changes_requested", notes="the maturity anchors are wrong",
            at_version=version, return_to="agent",
        )
        # A read satisfies the separate not-yet-reviewed gate (see test_approve_gate.py)
        # so the approval below succeeds for the reason this control is actually about.
        await record_script_review(
            conn, project_id=project["id"], script_id="SC-099", reviewer="bo",
            decision="reviewed", notes="", at_version=version,
        )
        await record_script_review(
            conn, project_id=project["id"], script_id="SC-099", reviewer="bo",
            decision="approved", notes="", at_version=version,
        )

    assert (await _row("SC-042"))[0] == "changes_requested"
    assert (await _row("SC-099"))[0] == "approved"

    # The regeneration, through the real write path - and it names SC-099 too, exactly as a
    # batch Maya writes would, so the control is genuinely written and not merely ignored.
    out2 = tool._run(
        operation="write", key="interview_scripts", agent_name="interaction_designer",
        value=json.dumps({"SC-042": _minimal_script("SC-042", "3.3.2", "Billing"),
                          "SC-099": _minimal_script("SC-099", "3.3.3", "Metering")}),
    )
    assert out2.startswith("Written to"), out2

    status, return_to, last_version, reviewed_at = await _row("SC-042")
    assert status == "pending", (
        "a regenerated script must not still read 'Sent back' in the review UI"
    )
    assert return_to is None, "and must not still be pointed at the agent"
    assert last_version > reviewed_at, "precondition: the regeneration really did land"

    assert (await _row("SC-099"))[0] == "approved", (
        "a script nobody sent back keeps the decision a reviewer recorded on it"
    )


@pytest.mark.asyncio
async def test_a_crew_other_than_assessment_design_never_queries_regeneration(
    assessment_project,
):
    """_fetch_regeneration_requests is gated on crew_name before it ever touches the
    database - only Maya's crew can act on a script send-back. Without the gate, every
    crew's tasks get her send-backs prepended.

    Final review, Important 3: the previous version of this test passed with the guard
    deleted. It ran against "some-other-slug", a project that does not exist, so
    `if not project: return ""` produced both the empty string and the un-called mock for
    entirely the wrong reason - and the docstring's claim that the gate fires "before it
    ever touches the database" was then false while the test still went green.

    So this drives a real project with a real send-back actually recorded against a real
    ledger row, and proves the data is reachable by asserting the positive case on the same
    slug in the same test. The probe delegates to the real function rather than stubbing
    it, so neither half of the assertion can be satisfied by an empty database.
    """
    import api.services.script_review_service as script_review_service
    from agents.tools.sqlite_state import SQLiteStateTool
    from api.services.run_service import _fetch_regeneration_requests

    slug = assessment_project
    tool = SQLiteStateTool(slug=slug, agent_name="interaction_designer", run_id=1)
    out = tool._run(
        operation="write", key="interview_scripts", agent_name="interaction_designer",
        value=json.dumps({"SC-042": _minimal_script("SC-042", "3.3.2", "Billing")}),
    )
    assert out.startswith("Written to"), out

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        cur = await conn.execute(
            "SELECT last_version FROM interview_script_ledger WHERE script_id=?",
            ("SC-042",),
        )
        current_version = (await cur.fetchone())[0]
        await script_review_service.record_script_review(
            conn, project_id=project["id"], script_id="SC-042", reviewer="bo",
            decision="changes_requested", notes="the maturity anchors are wrong",
            at_version=current_version, return_to="agent",
        )

    probe = AsyncMock(side_effect=script_review_service.scripts_awaiting_regeneration)
    with patch(
        "api.services.script_review_service.scripts_awaiting_regeneration", new=probe
    ):
        text = await _fetch_regeneration_requests(slug, "discovery_mapping")

    assert text == "", (
        "a non-Maya crew must receive no send-back block, on a project that really has one"
    )
    probe.assert_not_called()

    # The positive control, same slug, same send-back: without it, an empty result above
    # proves nothing about the gate.
    reachable = await _fetch_regeneration_requests(slug, "assessment_design")
    assert "SC-042" in reachable and "the maturity anchors are wrong" in reachable
