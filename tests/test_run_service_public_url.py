# tests/test_run_service_public_url.py
"""run_service.py:478 and :769 - the live defect Task 3 closes.

Both sites read `config.get("public_url", "")`, and `public_url` is not a field
`ProjectSettings` declares - `PATCH /{slug}/settings` could never set it, so the value
handed to Jordan's crew (the stakeholder management crew, both as a full crew and as a
standalone agent) has always been `""`. Both now read `platform_public_url()` instead.

Each test stores a distinctive URL through the real settings service and reads it back
out of the keyword argument the (mocked) crew factory actually receives - the property
that matters is what reaches the factory, not what platform_public_url() returns in
isolation, and the two dispatch paths (build_and_run_crew's stakeholder_management
branch and build_and_run_agent's stakeholder_manager branch) are genuinely different
code, so each is driven and asserted on its own rather than through a shared helper.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.config import get_settings
from api.services import platform_settings as ps

STORED_URL = "https://run-service-reader.example"


@pytest.fixture(autouse=True)
def _isolated_platform_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    ps.forget_platform_settings()
    yield
    ps.forget_platform_settings()
    get_settings.cache_clear()


async def _store_url(url: str = STORED_URL) -> None:
    from api.database import get_system_connection
    async with get_system_connection() as conn:
        await ps.save_platform_public_url(conn, url)


@pytest.mark.asyncio
async def test_stakeholder_management_crew_receives_the_stored_platform_public_url():
    """The full-crew path (build_and_run_crew, crew_name='stakeholder_management')."""
    from api.database import get_connection, insert_project

    slug = "run-service-stakemgmt"
    async with get_connection(slug) as conn:
        await insert_project(
            conn, slug=slug, llm_mode="standard", sector="rail", config_json="{}"
        )

    await _store_url()

    mock_crew = MagicMock()
    mock_crew.kickoff_async = AsyncMock(return_value="done")

    with patch(
        "api.services.run_service.load_project_config",
        return_value={"llm_mode": "standard", "sector": "rail"},
    ), patch(
        "agents.crews.stakeholder_management_crew.create_stakeholder_management_crew",
        return_value=mock_crew,
    ) as mock_factory:
        from api.services.run_service import build_and_run_crew
        result = await build_and_run_crew(slug, "stakeholder_management", run_id=1)

    assert result == "done"
    mock_factory.assert_called_once()
    assert mock_factory.call_args.kwargs["public_interview_url_base"] == (
        f"{STORED_URL}/dashboard/interview"
    )


@pytest.mark.asyncio
async def test_stakeholder_manager_standalone_agent_receives_the_stored_platform_public_url():
    """The standalone-agent path (build_and_run_agent, agent_key='stakeholder_manager') -
    reachable from the API even though CLAUDE.md notes the UI never calls it, and a
    genuinely separate branch from the crew path above (different factory, different
    task builder), so it needs its own proof rather than inheriting the crew test's."""
    from crewai import LLM
    from api.database import get_connection, insert_project

    slug = "run-service-standalone-stakemgr"
    async with get_connection(slug) as conn:
        await insert_project(
            conn, slug=slug, llm_mode="standard", sector="rail", config_json="{}"
        )

    await _store_url()

    fake_crew = MagicMock()
    fake_crew.kickoff_async = AsyncMock(return_value="done")

    with patch(
        "api.services.run_service.load_project_config",
        return_value={"llm_mode": "standard", "sector": "rail"},
    ), patch(
        "agents.model_registry.get_llm_for_agent", return_value=MagicMock(spec=LLM)
    ), patch(
        "agents.tools.registry.get_tools_for_agent", return_value=[]
    ), patch(
        "api.services.run_service.make_step_callback", return_value=None
    ), patch(
        "crewai.Crew", return_value=fake_crew
    ), patch(
        "agents.discovery.stakeholder_manager_agent.create_stakeholder_manager_task"
    ) as mock_task_factory:
        mock_task_factory.return_value = MagicMock()
        from api.services.run_service import build_and_run_agent
        result = await build_and_run_agent(slug, "stakeholder_manager", run_id=1)

    assert result == "done"
    mock_task_factory.assert_called_once()
    assert mock_task_factory.call_args.kwargs["public_interview_url_base"] == (
        f"{STORED_URL}/dashboard/interview"
    )


@pytest.mark.asyncio
async def test_nothing_stored_still_falls_back_to_the_environment_not_to_blank():
    """Before this task, `config.get("public_url", "")` was blank unconditionally -
    every dispatch, on every project. After it, an unconfigured deployment still gets a
    real URL (PUBLIC_URL's default), never the empty string the crew's own prompt
    branches on. Nothing is stored here; only the environment default applies."""
    from api.database import get_connection, insert_project

    slug = "run-service-stakemgmt-unconfigured"
    async with get_connection(slug) as conn:
        await insert_project(
            conn, slug=slug, llm_mode="standard", sector="rail", config_json="{}"
        )

    mock_crew = MagicMock()
    mock_crew.kickoff_async = AsyncMock(return_value="done")

    with patch(
        "api.services.run_service.load_project_config",
        return_value={"llm_mode": "standard", "sector": "rail"},
    ), patch(
        "agents.crews.stakeholder_management_crew.create_stakeholder_management_crew",
        return_value=mock_crew,
    ) as mock_factory:
        from api.services.run_service import build_and_run_crew
        await build_and_run_crew(slug, "stakeholder_management", run_id=1)

    base = mock_factory.call_args.kwargs["public_interview_url_base"]
    assert base, "must not be blank - that was the defect"
    # .rstrip('/'), not the raw settings value: platform_public_url() normalises its
    # environment fallback (Step 2), so this would fail on a *correct* implementation
    # the day a deployment's .env carries a trailing slash on PUBLIC_URL - the wrong
    # direction for a test to be wrong in.
    assert base == f"{get_settings().public_url.rstrip('/')}/dashboard/interview"
