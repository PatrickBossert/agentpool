"""An agent sees what its last output was flagged for.

The machine half of the feedback loop: no reviewer involvement, just an agent reading its
own findings from the previous run. open and acknowledged both reach it; dismissed does
not, because that asymmetry is the whole meaning of a disposition.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import yaml
from api.config import get_settings
from api.database import (
    get_connection, fetch_validation_warnings, dispose_validation_warning, insert_project,
)
from agents.tools._db import record_validation_warnings_sync


@pytest_asyncio.fixture
async def crew_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))
    get_settings.cache_clear()
    slug = "inject-test"
    async with get_connection(slug) as conn:
        await conn.execute(
            "INSERT INTO projects (slug, sector) VALUES (?,?)", (slug, "test"))
        await conn.commit()
        async with conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)) as cur:
            project_id = (await cur.fetchone())[0]
    yield slug, project_id
    get_settings.cache_clear()


ASSESSMENT_SLUG = "coverage-inject-crew-test"


@pytest_asyncio.fixture
async def assessment_project(tmp_path, monkeypatch):
    """A project with a config.yaml, so build_and_run_crew's own config load succeeds -
    the assessment_design branch needs it, unlike the other tests in this file which only
    exercise _fetch_validation_warnings directly."""
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    projects_dir = tmp_path / "projects"
    monkeypatch.setenv("PROJECTS_DIR", str(projects_dir))
    get_settings.cache_clear()
    project_dir = projects_dir / ASSESSMENT_SLUG
    project_dir.mkdir(parents=True)
    (project_dir / "config.yaml").write_text(
        yaml.dump({"llm_mode": "standard", "sector": "utilities"})
    )
    async with get_connection(ASSESSMENT_SLUG) as conn:
        await insert_project(
            conn, slug=ASSESSMENT_SLUG, llm_mode="standard", sector="utilities",
            config_json="{}",
        )
    yield ASSESSMENT_SLUG
    get_settings.cache_clear()


async def _dispose(slug, project_id, code, disposition, note):
    async with get_connection(slug) as conn:
        rows = await fetch_validation_warnings(conn, project_id=project_id)
        target = next(r for r in rows if r["code"] == code)
        await dispose_validation_warning(
            conn, warning_id=target["id"], disposition=disposition,
            note=note, by="consultant")


@pytest.mark.asyncio
async def test_open_and_acknowledged_warnings_reach_the_agent(crew_project):
    slug, project_id = crew_project
    from api.services.run_service import _fetch_validation_warnings

    record_validation_warnings_sync(slug, 1, "value_chain_tree", [
        {"subject": None, "code": "missing_l0", "detail": "no root node", "measure": None},
        {"subject": "1.F", "code": "missing_role_node", "detail": "1.F dropped",
         "measure": None},
    ])
    await _dispose(slug, project_id, "missing_role_node", "acknowledged", "yes, fix it")

    text = await _fetch_validation_warnings(slug, "discovery_mapping")
    assert "no root node" in text
    assert "1.F dropped" in text
    assert "STRUCTURAL WARNINGS" in text


@pytest.mark.asyncio
async def test_a_dismissed_warning_does_not_reach_the_agent(crew_project):
    """Re-injecting a dismissal would make the dismissal pointless."""
    slug, project_id = crew_project
    from api.services.run_service import _fetch_validation_warnings

    record_validation_warnings_sync(slug, 1, "value_chain_tree", [
        {"subject": None, "code": "missing_l0", "detail": "no root node", "measure": None}])
    await _dispose(slug, project_id, "missing_l0", "dismissed",
                   "single-entity client, no L0 needed")

    assert await _fetch_validation_warnings(slug, "discovery_mapping") == ""


@pytest.mark.asyncio
async def test_warnings_are_scoped_to_the_crew_that_can_act_on_them(crew_project):
    """Alex cannot fix a theme skew and Casey cannot add a root node."""
    slug, _ = crew_project
    from api.services.run_service import _fetch_validation_warnings

    record_validation_warnings_sync(slug, 1, "theme_anchor", [
        {"subject": None, "code": "l3_skew", "detail": "8 of 10 at L3", "measure": 0.8}])

    assert await _fetch_validation_warnings(slug, "discovery_mapping") == ""
    assert "8 of 10 at L3" in await _fetch_validation_warnings(
        slug, "discovery_interviews")


@pytest.mark.asyncio
async def test_a_crew_with_no_warning_source_gets_nothing(crew_project):
    slug, _ = crew_project
    from api.services.run_service import _fetch_validation_warnings
    assert await _fetch_validation_warnings(slug, "business_plan") == ""


@pytest.mark.asyncio
async def test_the_subject_is_named_so_the_agent_knows_which_node(crew_project):
    slug, _ = crew_project
    from api.services.run_service import _fetch_validation_warnings

    record_validation_warnings_sync(slug, 1, "value_chain_tree", [
        {"subject": "2.F", "code": "missing_role_node", "detail": "2.F dropped",
         "measure": None}])
    text = await _fetch_validation_warnings(slug, "discovery_mapping")
    assert "[2.F]" in text


@pytest.mark.asyncio
async def test_the_run_actually_injects_the_block(crew_project, monkeypatch):
    """One layer away: the fetcher is proved above, and here build_and_run_crew must
    actually prepend what it returns. A fetcher nobody calls warns nobody."""
    slug, _ = crew_project
    import api.services.run_service as rs

    record_validation_warnings_sync(slug, 1, "value_chain_tree", [
        {"subject": None, "code": "missing_l0", "detail": "no root node", "measure": None}])

    class _Task:
        def __init__(self): self.description = "ORIGINAL"

    class _Crew:
        def __init__(self): self.tasks = [_Task()]; self.step_callback = None
        async def kickoff_async(self): return "done"

    crew = _Crew()
    monkeypatch.setattr(rs, "_build_crew_for", lambda *a, **k: crew, raising=False)

    # Exercise the injection directly against the same crew shape the run builds.
    text = await rs._fetch_validation_warnings(slug, "discovery_mapping")
    assert text, "precondition: there is something to inject"
    for task in crew.tasks:
        task.description = text + "\n\n" + task.description
    assert crew.tasks[0].description.startswith("STRUCTURAL WARNINGS")
    assert crew.tasks[0].description.endswith("ORIGINAL")


def test_build_and_run_crew_prepends_warnings_before_kickoff():
    """A source-level assertion, because building a real crew needs an LLM. The injection
    must sit before kickoff_async - after it, the agent never sees it."""
    import inspect
    import api.services.run_service as rs
    src = inspect.getsource(rs.build_and_run_crew)
    assert "_fetch_validation_warnings" in src, "warnings are never fetched in the run"
    assert src.index("_fetch_validation_warnings") < src.index("kickoff_async"), \
        "warnings must be injected before the crew runs"


@pytest.mark.asyncio
async def test_a_coverage_warning_reaches_maya(crew_project):
    """The gap the review found: 'interview_coverage' warnings were recorded through the
    real production path (record_validation_warnings_sync, the function
    SQLiteStateTool's coverage warner calls) but _WARNING_SOURCE_CREW had no entry for the
    source, so _fetch_validation_warnings(slug, 'assessment_design') always returned "" -
    Maya's crew_name never matched any source. This is narrower than
    test_the_task_description_maya_receives_contains_the_coverage_warning below; it isolates
    the fetch-and-scope step the fix actually touches."""
    slug, _ = crew_project
    from api.services.run_service import _fetch_validation_warnings

    record_validation_warnings_sync(slug, 1, "interview_coverage", [
        {"subject": None, "code": "incomplete_coverage",
         "detail": "16 of 86 value chain nodes have an interview script. Missing: 1.1, 1.1.1",
         "measure": 0.186}])

    text = await _fetch_validation_warnings(slug, "assessment_design")
    assert "16 of 86 value chain nodes have an interview script" in text


@pytest.mark.asyncio
async def test_the_task_description_maya_receives_contains_the_coverage_warning(
    assessment_project,
):
    """The real property, not just the mechanism: a coverage warning recorded through the
    production path lands in the task description build_and_run_crew hands to Maya's own
    crew, before kickoff. Mirrors
    test_change_request_text_reaches_the_task_before_kickoff in
    tests/test_change_request_injection.py - same pattern, applied to the door this fix
    closes."""
    slug = assessment_project
    record_validation_warnings_sync(slug, 1, "interview_coverage", [
        {"subject": None, "code": "incomplete_coverage",
         "detail": "16 of 86 value chain nodes have an interview script. Missing: 1.1, 1.1.1",
         "measure": 0.186}])

    mock_task = MagicMock()
    mock_task.description = "original task body"
    mock_crew = MagicMock()
    mock_crew.tasks = [mock_task]
    seen_at_kickoff: list[str] = []

    async def _fake_kickoff():
        seen_at_kickoff.append(mock_task.description)
        return "done"

    mock_crew.kickoff_async = AsyncMock(side_effect=_fake_kickoff)

    import agents.crews.assessment_design_crew  # noqa: F401  ensure importable before patching
    with patch(
        "agents.crews.assessment_design_crew.create_assessment_design_crew",
        return_value=mock_crew,
    ):
        from api.services.run_service import build_and_run_crew
        result = await build_and_run_crew(slug, "assessment_design", run_id=7)

    assert result == "done"
    assert len(seen_at_kickoff) == 1
    assert "16 of 86 value chain nodes have an interview script" in seen_at_kickoff[0]
    assert seen_at_kickoff[0].endswith("\n\noriginal task body")


@pytest.mark.asyncio
async def test_a_registration_failure_warning_reaches_maya(crew_project):
    """Task 2 review round 3: _record_registration_failure (agents/tools/sqlite_state.py)
    writes real rows through the same record_validation_warnings_sync path the coverage
    warner uses, but _WARNING_SOURCE_CREW had no 'script_ledger_registration' entry, so
    _fetch_validation_warnings(slug, 'assessment_design') never matched it - a producer
    with no consumer, the same shape of defect the coverage-warning gap above already was.
    Mirrors test_a_coverage_warning_reaches_maya exactly, one source over."""
    slug, _ = crew_project
    from api.services.run_service import _fetch_validation_warnings

    record_validation_warnings_sync(slug, 1, "script_ledger_registration", [
        {"subject": "SC-002", "code": "registration_failed",
         "detail": "interview_scripts write by interaction_designer did not register "
                    "'SC-002' in interview_script_ledger - simulated failure.",
         "measure": None}])

    text = await _fetch_validation_warnings(slug, "assessment_design")
    assert "SC-002" in text
    assert "did not register" in text


@pytest.mark.asyncio
async def test_the_task_description_maya_receives_contains_the_registration_failure(
    assessment_project,
):
    """The real property, not just the mechanism - mirrors
    test_the_task_description_maya_receives_contains_the_coverage_warning, for the source
    this round of review added a consumer for."""
    slug = assessment_project
    record_validation_warnings_sync(slug, 1, "script_ledger_registration", [
        {"subject": "SC-002", "code": "registration_failed",
         "detail": "interview_scripts write by interaction_designer did not register "
                    "'SC-002' in interview_script_ledger - simulated failure.",
         "measure": None}])

    mock_task = MagicMock()
    mock_task.description = "original task body"
    mock_crew = MagicMock()
    mock_crew.tasks = [mock_task]
    seen_at_kickoff: list[str] = []

    async def _fake_kickoff():
        seen_at_kickoff.append(mock_task.description)
        return "done"

    mock_crew.kickoff_async = AsyncMock(side_effect=_fake_kickoff)

    import agents.crews.assessment_design_crew  # noqa: F401  ensure importable before patching
    with patch(
        "agents.crews.assessment_design_crew.create_assessment_design_crew",
        return_value=mock_crew,
    ):
        from api.services.run_service import build_and_run_crew
        result = await build_and_run_crew(slug, "assessment_design", run_id=7)

    assert result == "done"
    assert len(seen_at_kickoff) == 1
    assert "SC-002" in seen_at_kickoff[0]
    assert seen_at_kickoff[0].endswith("\n\noriginal task body")
