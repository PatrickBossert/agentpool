# tests/test_run_service.py
"""Unit tests for the build_and_run_crew shared helper."""
import pytest
from unittest.mock import patch


@pytest.fixture
def fake_config(tmp_path, monkeypatch):
    """Write a minimal config.yaml and point PROJECTS_DIR and DATABASE_DIR at tmp_path.

    DATABASE_DIR too, per CLAUDE.md's persistent-database trap: `build_and_run_crew` opens the
    project database on its way to the change requests and validation warnings it injects, and
    against the shared `/tmp/agentpool_test` that would leave a stray `acme.db` behind for
    every later run to read.
    """
    import api.config as cfg
    cfg.get_settings.cache_clear()
    import yaml
    project_dir = tmp_path / "acme"
    project_dir.mkdir()
    (project_dir / "config.yaml").write_text(
        yaml.dump({
            "llm_mode": "standard",
            "sector": "transport",
            "value_stream_labels": ["Ops"],
            "stakeholder_groups": ["IT"],
            "roadmap_time_axis": "quarters",
        })
    )
    db_dir = tmp_path / "data"
    db_dir.mkdir()
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_DIR", str(db_dir))
    cfg.get_settings.cache_clear()
    yield tmp_path
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_build_and_run_crew_builds_and_runs_the_requirements_crew(fake_config):
    """Dispatched against the real factory, so the call site is what is under test.

    This test used to assert `create_requirements_crew` was called with `discovery_brief`,
    `discovery_links` and `priority_doc_names` - against a `MagicMock` factory, which accepts
    anything. The real factory takes none of the three, so every dispatch of this crew raised
    `TypeError` before an agent was built while the test that "covered" the branch passed. Only
    `kickoff_async` is stubbed here: the factory, the two agents and their tasks are the real
    ones, so an argument the factory does not take fails here exactly as it does in production.
    """
    from crewai import Crew
    import agents.crews.requirements_crew as requirements_crew

    with patch.object(requirements_crew, "get_tools_for_agent", return_value=[]), \
         patch.object(Crew, "kickoff_async", autospec=True, return_value="done") as kickoff:
        from api.services.run_service import build_and_run_crew
        result = await build_and_run_crew("acme", "requirements", run_id=1)

    assert result == "done"
    kickoff.assert_awaited_once()
    built = kickoff.await_args.args[0]
    assert [agent.role for agent in built.agents] == [
        "Requirements Capture Specialist", "Requirements Analyst",
    ]


@pytest.mark.asyncio
async def test_build_and_run_crew_raises_on_unknown_crew(fake_config):
    from api.services.run_service import build_and_run_crew
    with pytest.raises(ValueError, match="Unknown crew"):
        await build_and_run_crew("acme", "nonexistent_crew", run_id=1)
