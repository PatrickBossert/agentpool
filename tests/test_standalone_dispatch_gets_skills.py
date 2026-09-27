# tests/test_standalone_dispatch_gets_skills.py
"""A standalone agent runs on the same prompt as the crew containing it.

`build_and_run_agent` fetched no library skills, so dispatching one agent alone gave it a
materially different prompt from the identical agent inside `build_and_run_crew`. CLAUDE.md
recorded it as tech debt on the grounds that the path was unreachable from the UI - `runAgent`
is defined in `endpoints.ts` and called by nothing - which was true and was not the whole
story: it is reachable from the API, and it is the path a consultant reaches for to synthesise
a finished interview programme, because the crew path would have Avery block on a human gate.

Found when it mattered. Casey's `Theme Extraction` skill reads *"only flag a theme if it
appears across multiple transcripts - single-respondent observations belong in 'individual
perspectives' ... never extrapolate a theme from one voice"*, which is the instruction that
decides whether his output is usable rather than a list of impressions. A standalone run of the
first real collation would have been made without it, and the result would have been read as
Casey's best work.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.services import run_service


@pytest.mark.asyncio
async def test_a_standalone_agent_is_given_the_library_skills(monkeypatch, tmp_path):
    """The skills reach the **task description**, which is what the model is sent.

    Asserted on `task.description` rather than on `_fetch_skill_notes` being called, because a
    call whose result is discarded is exactly the defect being repaired - the function was
    always there and always correct; nothing on this path invoked it.
    """
    captured: dict = {}

    class _Crew:
        def __init__(self, *_, tasks, **__):
            captured["description"] = tasks[0].description
        step_callback = None
        async def kickoff_async(self):
            return "done"

    task = MagicMock()
    task.description = "ORIGINAL TASK BODY"
    agent = MagicMock()

    monkeypatch.setattr(run_service, "_fetch_skill_notes", AsyncMock(return_value="SKILL BLOCK"))
    monkeypatch.setattr(run_service, "load_project_config", lambda _p: {})
    # Patched at their **source modules**, not on `run_service`: `build_and_run_agent`
    # imports both inside the function body, so the lookup happens there on every call and a
    # `setattr` on `run_service` would bind a name nothing reads. CLAUDE.md records four crew
    # tests that patched where a function was defined while the module bound its own
    # reference; this is the mirror image, and the same question answers it - where is the
    # name looked up?
    monkeypatch.setattr("agents.model_registry.get_llm_for_agent", lambda *a, **k: MagicMock())
    monkeypatch.setattr("agents.tools.registry.get_tools_for_agent", lambda *a, **k: [])
    monkeypatch.setattr(run_service, "make_step_callback", lambda *a, **k: None)

    with patch("crewai.Crew", _Crew), patch("crewai.Process"), patch(
        "agents.discovery.synthesis_analyst.create_synthesis_analyst", return_value=agent
    ), patch(
        "agents.discovery.synthesis_analyst.create_synthesis_analyst_task", return_value=task
    ), patch.object(
        run_service, "fetch_project", AsyncMock(return_value={"id": 1})
    ), patch(
        "api.database.fetch_interview_sessions_status_for_project",
        AsyncMock(return_value={"completed": 3}),
    ):
        await run_service.build_and_run_agent("a-project", "synthesis_analyst", run_id=1)

    assert captured["description"].startswith("SKILL BLOCK"), (
        "the standalone path ran the agent on a prompt the crew would not have used"
    )
    assert "ORIGINAL TASK BODY" in captured["description"], (
        "the skills replaced the task rather than preceding it"
    )


@pytest.mark.asyncio
async def test_the_standalone_path_asks_for_the_same_crew_the_crew_path_would(monkeypatch):
    """Scoped by crew, deliberately, so the two paths cannot disagree.

    `build_and_run_crew` prepends one block built from the whole crew's assignments to every
    task. Narrowing the standalone fetch to the single agent would be defensible on its own
    terms and would reintroduce exactly the divergence this repairs, in the other direction -
    so the crew name is asserted rather than left to read as an accident.
    """
    asked: list[str] = []

    async def _fake(crew_name, slug):
        asked.append(crew_name)
        return ""

    class _Crew:
        def __init__(self, *_, **__): pass
        step_callback = None
        async def kickoff_async(self): return "done"

    monkeypatch.setattr(run_service, "_fetch_skill_notes", _fake)
    monkeypatch.setattr(run_service, "load_project_config", lambda _p: {})
    # Patched at their **source modules**, not on `run_service`: `build_and_run_agent`
    # imports both inside the function body, so the lookup happens there on every call and a
    # `setattr` on `run_service` would bind a name nothing reads. CLAUDE.md records four crew
    # tests that patched where a function was defined while the module bound its own
    # reference; this is the mirror image, and the same question answers it - where is the
    # name looked up?
    monkeypatch.setattr("agents.model_registry.get_llm_for_agent", lambda *a, **k: MagicMock())
    monkeypatch.setattr("agents.tools.registry.get_tools_for_agent", lambda *a, **k: [])
    monkeypatch.setattr(run_service, "make_step_callback", lambda *a, **k: None)

    with patch("crewai.Crew", _Crew), patch("crewai.Process"), patch(
        "agents.discovery.synthesis_analyst.create_synthesis_analyst", return_value=MagicMock()
    ), patch(
        "agents.discovery.synthesis_analyst.create_synthesis_analyst_task",
        return_value=MagicMock(description="x"),
    ), patch.object(
        run_service, "fetch_project", AsyncMock(return_value={"id": 1})
    ), patch(
        "api.database.fetch_interview_sessions_status_for_project",
        AsyncMock(return_value={"completed": 3}),
    ):
        await run_service.build_and_run_agent("a-project", "synthesis_analyst", run_id=1)

    assert asked == [run_service.AGENT_CREW_NAME["synthesis_analyst"]]
    assert asked == ["discovery_interviews"], (
        "Casey's crew is discovery_interviews - if this moved, the skills a standalone run "
        "receives moved with it"
    )
