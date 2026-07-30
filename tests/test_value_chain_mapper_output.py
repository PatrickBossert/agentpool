# tests/test_value_chain_mapper_output.py
"""Alex emits the model, not a diagram.

Leave him emitting Mermaid and his next run overwrites the model with a rendering, and the
editor has nothing to edit.
"""
from unittest.mock import MagicMock

import pytest
from crewai import LLM

from agents.discovery.value_chain_mapper import (
    create_value_chain_mapper,
    create_value_chain_mapper_task,
)


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
    """A bare 'column' mention isn't enough - Alex must know columns step by 10 and what a
    shared vs. an offset column between two contributions of the same activity means."""
    assert "steps of 10" in task_text
    assert "10, 20, 30" in task_text
    assert "concurrently" in task_text, "does not explain what a shared column means"
    assert "handoff" in task_text, "does not explain what an offset column means"


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
