# tests/test_value_chain_mapper_output.py
"""Alex emits the model, not a diagram.

Leave him emitting Mermaid and his next run overwrites the model with a rendering, and the
editor has nothing to edit.

Three separate paths can each tell him to draw one, so all three are checked here: the task
text, the approved skills injected into that text by run_service, and the tools he holds. A
test that greps only the task description cannot see the other two.
"""
from unittest.mock import MagicMock

import pytest
from crewai import LLM

from agents.discovery.value_chain_mapper import (
    create_value_chain_mapper,
    create_value_chain_mapper_task,
)
from agents.tools.registry import get_tools_for_agent
from api.services.skills_service import BASELINE_SKILLS

MAPPER = "Value Chain Mapper"


def _skills_for(display_name: str) -> list[dict]:
    return [s for s in BASELINE_SKILLS if display_name in s["agents"]]


@pytest.fixture
def task_text() -> str:
    agent = create_value_chain_mapper(slug="t", llm=MagicMock(spec=LLM), tools=[])
    task = create_value_chain_mapper_task(agent=agent)
    return (task.description + "\n" + task.expected_output).lower()


def test_the_task_no_longer_asks_for_a_mermaid_diagram(task_text):
    for phrase in ("mermaid", "flowchart lr", "classdef", "subgraph"):
        assert phrase not in task_text, f"still asks for {phrase!r}"


def test_the_task_asks_for_the_model_by_its_output_type(task_text):
    assert "value_chain_model" in task_text


def test_the_task_names_every_part_of_the_model(task_text):
    for key in (
        "parties", "segments", "activities", "contributions", "tasks", "propositions",
        "links", "column", "attribution",
    ):
        assert key in task_text, f"does not mention {key}"


def test_the_task_asks_for_descriptions(task_text):
    """Descriptions are the point - they have never existed."""
    assert "description" in task_text


def test_the_task_explains_a_contribution(task_text):
    """Alex has to understand that one activity can have several parties' parts."""
    assert "contribution" in task_text
    assert "party" in task_text


def test_the_task_explains_the_column_step_of_10_rule(task_text):
    """A bare 'column' mention isn't enough - Alex must know columns step by 10, and that a
    column belongs to the activity rather than to each party's reading of it.

    This previously also required the prompt to explain 'concurrently' and 'handoff' as the
    meanings of a shared versus an offset column between two contributions of the same
    activity. That distinction no longer exists: validate_model refuses an activity split
    across columns, so a handoff between parties is two activities, and a prompt still
    teaching the offset would produce models the write tool rejects.
    """
    assert "steps of 10" in task_text
    assert "10, 20, 30" in task_text
    assert "same column" in task_text, "does not say an activity's contributions share one"


def test_the_task_ties_model_ids_to_the_registry(task_text):
    """The model's activities[].id (etc.) must be the same IDs as the registry loaded in
    step 0, not a fresh numbering - otherwise every downstream reference to an activity by
    ID points somewhere else. api/services/value_chain_migration.py:69-79 already treats a
    registry L2 entry's id as the model's activities[].id; this is the same ID space."""
    for field in ("segments[].id", "activities[].id", "tasks[].id"):
        assert field in task_text, f"does not tie {field} to the registry"
    assert "registry you loaded in step 0" in task_text
    assert "l1 registry entry becomes a segment" in task_text
    assert "l2 entry becomes an activity" in task_text
    assert "l3 entry becomes a task" in task_text


def test_the_task_requires_every_activity_to_carry_a_contribution(task_text):
    """api/services/value_chain_model.py's validate_model refuses a model in which an
    activity carries no contribution, but the mapper writes its model through SQLiteStateTool
    rather than save_model, so nothing checks this on the way in. Such an activity belongs to
    no party's lane, so the grid renders it nowhere - and every save from then on is refused,
    naming an activity that appears on screen nowhere.

    No UI mutation can reach this state (removeParty is gated by isLastContribution) and the
    migration cascade closes the other route, so the crew path is the only one left open.
    """
    assert "at least one contribution" in task_text
    assert "activity with no contribution" in task_text


def test_the_task_requires_one_party_not_to_repeat_a_column_within_a_segment(task_text):
    """The grid renders one card per (party lane, column) cell, so a second contribution of
    the same party at the same column of the same segment never appears at all - and every
    save is then refused with "two contributions occupy column N in party P's lane"."""
    assert "must not repeat a column" in task_text
    assert "same party" in task_text
    assert "same segment" in task_text


def test_the_mapper_holds_no_tool_that_can_render_a_diagram():
    """The task text is only one of the paths. Leave him the tool and he can still write a
    value_chain_v13.md whatever the task says, which is the outcome this branch exists to
    prevent."""
    tools = get_tools_for_agent("value_chain_mapper", slug="t", sector="transport")
    offenders = [
        type(tool).__name__ for tool in tools
        if "mermaid" in type(tool).__name__.lower()
        or "mermaid" in (getattr(tool, "name", "") or "").lower()
    ]
    assert offenders == [], f"still holds {offenders}"


def test_no_seeded_skill_tells_the_mapper_to_produce_a_diagram():
    """run_service injects every approved skill for a crew's agents into the task text as
    "AGENT SKILLS (apply these capabilities in your work)", so a skill saying "produce a
    valid Mermaid diagram alongside every JSON output" instructs him regardless of what the
    task itself asks for."""
    offenders = [
        s["name"] for s in _skills_for(MAPPER)
        if any(word in s["description"].lower() for word in ("mermaid", "diagram", "flowchart"))
    ]
    assert offenders == [], f"skills still ask for a diagram: {offenders}"


def test_the_enterprise_architect_keeps_diagram_rendering():
    """Guards the correction against overreach - that agent legitimately still draws."""
    architect = [s["name"] for s in _skills_for("Enterprise Architect")]
    assert "Diagram Rendering" in architect

    tools = get_tools_for_agent("enterprise_architect", slug="t", sector="transport")
    assert any("mermaid" in type(tool).__name__.lower() for tool in tools)


# ---------------------------------------------------------------------------
# Where the instructions conflicted with what validation now enforces.
#
# Prompt tests are brittle and most wording does not deserve one. These do: two of the five
# defects in the run that rebuilt the whole chain were the prompt being *obeyed*. It
# described segments as process stages, and it told the agent that offset columns between
# two parties on one activity mean a handoff - which validate_model now refuses, so leaving
# it in place would have the agent writing models the tool rejects, in a loop it could not
# escape by following its instructions.
# ---------------------------------------------------------------------------


@pytest.fixture
def raw_task_text() -> str:
    """The description with its case intact - some of these rules are shouted."""
    agent = create_value_chain_mapper(slug="t", llm=MagicMock(spec=LLM), tools=[])
    return create_value_chain_mapper_task(agent=agent).description


def test_the_task_does_not_instruct_the_handoff_that_validation_refuses(raw_task_text):
    assert "handoff from one party to the next" not in raw_task_text


def test_the_task_states_that_one_activity_has_one_column(raw_task_text):
    assert "same column" in raw_task_text
    # Named as validation names it, so a refusal the agent reads matches a rule it was given.
    assert "split across columns" in raw_task_text


def test_segments_are_described_as_value_chains_not_process_stages(raw_task_text):
    # The exact wording that produced the rebuild. If it returns, so does the defect.
    assert "Acquisition, Delivery, Monitoring" not in raw_task_text


def test_the_task_still_forbids_a_party_repeating_a_column(raw_task_text):
    # The two column rules are different and both hold. Replacing one with the other would
    # trade this defect for the collision that made the model unsaveable.
    assert "MUST NOT repeat a column" in raw_task_text


def test_the_task_requires_every_contribution_to_decompose(raw_task_text):
    # Enforced at the write path, so the prompt must say it - an agent refused by a rule it
    # was never given can only guess its way out.
    assert "at least one" in raw_task_text
    assert "no activity of its own" in raw_task_text
