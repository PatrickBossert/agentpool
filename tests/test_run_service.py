# tests/test_run_service.py
"""Unit tests for the build_and_run_crew shared helper."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.fixture
def fake_config(tmp_path, monkeypatch):
    """Write a minimal config.yaml and point PROJECTS_DIR at tmp_path."""
    import api.config as cfg
    cfg.get_settings.cache_clear()
    import yaml, os
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
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    cfg.get_settings.cache_clear()
    yield tmp_path
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_build_and_run_crew_dispatches_discovery(fake_config):
    import agents.crews.discovery_crew  # ensure module is in sys.modules before patching
    mock_crew = MagicMock()
    mock_crew.kickoff_async = AsyncMock(return_value="done")
    with patch("agents.crews.discovery_crew.create_discovery_crew", return_value=mock_crew) as mock_factory:
        from api.services.run_service import build_and_run_crew
        result = await build_and_run_crew("acme", "discovery", run_id=1)
    mock_factory.assert_called_once_with(slug="acme", run_id=1, llm_mode="standard", sector="transport")
    mock_crew.kickoff_async.assert_awaited_once()
    assert result == "done"


@pytest.mark.asyncio
async def test_build_and_run_crew_raises_on_unknown_crew(fake_config):
    from api.services.run_service import build_and_run_crew
    with pytest.raises(ValueError, match="Unknown crew"):
        await build_and_run_crew("acme", "nonexistent_crew", run_id=1)
