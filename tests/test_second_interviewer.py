# tests/test_second_interviewer.py
"""Laura Nelson - a second voice on `discovery_interviews`, and not a second brief.

Two properties, and they pull against each other, which is why both are asserted here rather
than left to the registries that each hold half:

- She is a **different person**: her own permanent `agent_id`, her own display name, and above
  all her own default voice. A second interviewer who sounds like the first is not a choice.
- She does the **same job**: one goal, one backstory, one interviewing task between the two of
  them. Divergent interviewing instructions would make the transcripts incomparable, and it is
  Casey who would pay - he reasons across every answer in a campaign, so two instruments would
  leave him comparing the interviews rather than the organisations.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from crewai import LLM

from agents.identity import AGENT_IDENTITY
from api.services.agent_config_service import resolve_agent_config

AVERY = "stakeholder_interviewer"
LAURA = "second_interviewer"

# A slug with no database on disk. `resolve_agent_config` resolves every default for one and
# creates nothing, which is what makes this the honest way to ask what the defaults are.
UNCONFIGURED = "no-such-project-second-interviewer"


# ── She has her own voice, and it is not his ──────────────────────────────────

@pytest.mark.asyncio
async def test_each_interviewer_resolves_their_own_default_voice_and_the_two_differ():
    """The point of a second interviewer.

    Asserted through `resolve_agent_config` rather than by reading `AGENT_IDENTITY`, because
    the resolver is what the session stamp and the portal will ask - a default that only the
    registry knows about is the defect Task 1 corrected, in a new place.
    """
    avery = await resolve_agent_config(UNCONFIGURED, AVERY)
    laura = await resolve_agent_config(UNCONFIGURED, LAURA)

    assert avery["voice_id"], "Avery resolves no default voice"
    assert laura["voice_id"], "Laura resolves no default voice"
    assert laura["voice_id"] != avery["voice_id"], (
        "both interviewers resolve the same voice, so choosing between them would change the "
        "name a participant reads and nothing they hear"
    )


@pytest.mark.asyncio
async def test_laura_resolves_her_own_name_and_no_borrowed_face():
    laura = await resolve_agent_config(UNCONFIGURED, LAURA)
    assert laura["display_name"] == "Laura Nelson"
    # None rather than somebody else's headshot. `AgentFace` renders her initials instead.
    assert laura["image_url"] is None


def test_her_id_does_not_encode_the_thing_that_may_change():
    """`agent_id` is permanent; the voice and the persona are not.

    An id spelled `female_interviewer` would write a fact about the voice into the one field
    that may never be rewritten - and the selection reads the voices' own metadata, so it would
    buy nothing even while it was true.
    """
    for banned in ("female", "male", "laura", "nelson", "voice"):
        assert banned not in LAURA, f"the permanent id names {banned!r}"
    assert LAURA in AGENT_IDENTITY


# ── She does the same job ─────────────────────────────────────────────────────

def _agents() -> tuple:
    from agents.discovery.second_interviewer import create_second_interviewer
    from agents.discovery.stakeholder_interviewer import create_stakeholder_interviewer

    llm = MagicMock(spec=LLM)
    return (
        create_stakeholder_interviewer(slug="t", llm=llm, tools=[]),
        create_second_interviewer(slug="t", llm=llm, tools=[]),
    )


def test_the_two_interviewers_are_given_the_same_goal_and_the_same_backstory():
    avery, laura = _agents()
    assert laura.goal == avery.goal
    assert laura.backstory == avery.backstory


def test_only_their_roles_differ():
    """The role is what a reader and `inferAgentStatuses` tell them apart by, so it is the one
    thing that cannot be shared - and the one thing that shapes no instruction."""
    avery, laura = _agents()
    assert laura.role != avery.role
    assert laura.role == "Second Interviewer"


def test_her_module_declares_no_second_interviewing_prompt():
    """A goal or backstory typed out in her module would pass the equality above on the day it
    was written and drift from his on any day after. `build_interviewer` is what makes the
    sharing structural, so this asserts that her module carries no prompt text of its own.
    """
    source = Path("agents/discovery/second_interviewer.py").read_text()
    assert "build_interviewer" in source
    for absent in ("goal=", "backstory=", "Task("):
        assert absent not in source, (
            f"agents/discovery/second_interviewer.py declares {absent!r} - the interviewing "
            f"brief belongs in stakeholder_interviewer.py, once"
        )


def test_she_holds_exactly_the_tools_he_holds():
    from agents.tools.registry import get_tools_for_agent

    def classes(agent_id: str) -> list[str]:
        tools = get_tools_for_agent(agent_id, slug="x", run_id=1, sector="test")
        return [type(t).__name__ for t in tools]

    assert classes(LAURA) == classes(AVERY)


def test_they_run_on_the_same_tier():
    from agents.model_registry import AGENT_TIER

    assert AGENT_TIER[LAURA] == AGENT_TIER[AVERY] == "fast"


# ── She is on the crew, and the crew still runs one interview programme ───────

def test_the_crew_builds_both_interviewers_and_gives_the_task_to_one():
    """Two interviewers is a choice of voice, not two rounds of interviews.

    The task count is the half that matters: a factory that gave each of them the interviewing
    task would build a crew that ran the whole programme twice, and every membership
    declaration would still agree with itself.
    """
    import agents.crews.discovery_interviews_crew as module

    with patch.object(module, "get_tools_for_agent", return_value=[]):
        crew = module.create_discovery_interviews_crew(
            slug="t", run_id=1, sector="rail", stakeholder_assignments=[],
            llm=MagicMock(spec=LLM),
        )

    assert [a.role for a in crew.agents] == [
        "Interview Coordinator", "Stakeholder Interviewer", "Second Interviewer",
        "Synthesis Analyst",
    ]
    assert len(crew.tasks) == 3
    assert [t.agent.role for t in crew.tasks] == [
        "Interview Coordinator", "Stakeholder Interviewer", "Synthesis Analyst",
    ]


def test_the_factory_asks_the_registry_for_her_tools_under_her_own_id():
    """Not Avery's, which would give her his `SQLiteStateTool` identity and make her writes
    claim to be his."""
    import agents.crews.discovery_interviews_crew as module

    asked: list[str] = []
    with patch.object(module, "get_tools_for_agent", side_effect=lambda n, **k: asked.append(n) or []):
        module.create_discovery_interviews_crew(
            slug="t", run_id=1, sector="rail", stakeholder_assignments=[],
            llm=MagicMock(spec=LLM),
        )
    assert asked.count(LAURA) == 1
    assert asked.count(AVERY) == 1


# ── What Task 3 must clear before she can take the task ───────────────────────

def test_handing_her_averys_task_verbatim_would_be_refused_twice():
    """Recorded, not repaired - and recorded so it is met here rather than at run time.

    The interviewing task names `agent_name='stakeholder_interviewer'` in every state write.
    `SQLiteStateTool` refuses a write whose claimed agent disagrees with the tool's own, and
    `check_write` refuses one whose agent is not the output's declared owner. Both refuse
    loudly, which is the right direction, but both refuse - so selecting Laura is not merely a
    matter of passing her the task, and the next task should meet that here rather than in a
    run.
    """
    from agents.discovery.stakeholder_interviewer import create_stakeholder_interviewer_task
    from agents.tools.ownership import check_write

    avery, _ = _agents()
    task = create_stakeholder_interviewer_task(agent=avery, context_tasks=[])
    assert f"agent_name='{AVERY}'" in task.description
    assert f"agent_name='{LAURA}'" not in task.description

    refusal = check_write("interview_transcripts", LAURA)
    assert refusal is not None and AVERY in refusal


def test_the_shared_builder_takes_the_role_and_nothing_else_that_shapes_the_work():
    """`build_interviewer(role, slug, llm, tools)`. A `goal` or `backstory` parameter would be
    the second brief arriving by the back door."""
    from agents.discovery.stakeholder_interviewer import build_interviewer

    assert list(inspect.signature(build_interviewer).parameters) == ["role", "slug", "llm", "tools"]
