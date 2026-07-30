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
    for key in ("parties", "segments", "activities", "contributions", "tasks", "links"):
        assert key in task_text, f"does not mention {key}"


def test_the_task_asks_for_descriptions(task_text):
    """Descriptions are the point - they have never existed."""
    assert "description" in task_text


def test_the_task_explains_a_contribution(task_text):
    """Alex has to understand that one activity can have several parties' parts."""
    assert "contribution" in task_text
    assert "party" in task_text
