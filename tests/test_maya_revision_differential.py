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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import yaml

from api.database import get_connection, insert_project
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


@pytest.mark.asyncio
async def test_a_crew_other_than_assessment_design_never_queries_regeneration(tmp_path, monkeypatch):
    """_fetch_regeneration_requests is gated on crew_name before it ever touches the
    database - only Maya's crew can act on a script send-back."""
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    from api.services.run_service import _fetch_regeneration_requests

    with patch(
        "api.services.script_review_service.scripts_awaiting_regeneration",
        new=AsyncMock(return_value=[
            {"script_id": "SC-042", "node_id": "3.3.2", "node_label": "Billing",
             "notes": "should never be reached"}]),
    ) as mocked:
        text = await _fetch_regeneration_requests("some-other-slug", "discovery_mapping")

    assert text == ""
    mocked.assert_not_called()
    get_settings.cache_clear()
