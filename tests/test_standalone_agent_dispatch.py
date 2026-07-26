# tests/test_standalone_agent_dispatch.py
"""Every agent advertised for standalone dispatch must actually be dispatchable.

`POST /projects/{slug}/run` with an `agent` key checks membership of
AGENT_CREW_NAME, then creates a crew_run row and fires dispatch_agent. But the
branch that actually builds the agent lives in a separate table inside
build_and_run_agent. When the two disagree, the request is accepted, a run row is
created, and the run dies instantly with "Unknown agent key" - the user sees a
failed run and no output.

That is exactly what happened to Maya Patel (interaction_designer) and Jordan
Williams (stakeholder_manager): both were advertised as dispatchable and neither
had a branch.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from crewai import LLM

from api.services.run_service import AGENT_CREW_NAME


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_key", sorted(AGENT_CREW_NAME))
async def test_every_advertised_agent_has_a_dispatch_branch(agent_key):
    """build_and_run_agent must not reject any key that AGENT_CREW_NAME advertises."""
    from api.services.run_service import build_and_run_agent

    fake_crew = MagicMock()
    fake_crew.kickoff_async = AsyncMock(return_value="done")

    with patch("api.services.run_service.load_project_config", return_value={
                "llm_mode": "standard",
                "sector": "infrastructure asset management",
                "value_stream_labels": ["Inbound", "Outbound"],
                "public_url": "https://example.test",
            }), \
         patch("api.services.run_service.get_settings") as m_settings, \
         patch("agents.llm.get_crew_llm", return_value=MagicMock(spec=LLM)), \
         patch("agents.tools.registry.get_tools_for_agent", return_value=[]), \
         patch("api.services.run_service.make_step_callback", return_value=None), \
         patch("crewai.Crew", return_value=fake_crew):
        m_settings.return_value.projects_dir = "/tmp"

        result = await build_and_run_agent("test-slug", agent_key, run_id=1)

    assert result == "done", f"{agent_key} did not reach crew execution"
    fake_crew.kickoff_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_agent_key_still_rejected():
    """A key that is genuinely unknown must still raise, not silently no-op."""
    from api.services.run_service import build_and_run_agent

    with pytest.raises(ValueError, match="not eligible for standalone dispatch"):
        await build_and_run_agent("test-slug", "not_a_real_agent", run_id=1)


def test_questionnaire_builder_is_not_advertised_for_standalone_dispatch():
    """Its agent module was removed when questionnaires moved inline to the interview.

    The crew-name alias in build_and_run_crew stays - stored crew_run rows in other
    environments may still carry it - but there is no agent left to dispatch, so
    advertising it here would accept a request that cannot succeed.
    """
    assert "questionnaire_builder" not in AGENT_CREW_NAME
