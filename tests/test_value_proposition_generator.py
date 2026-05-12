"""Tests for the updated value_proposition_generator task schema."""
from unittest.mock import MagicMock, patch


def test_task_description_includes_activity_refs():
    """Task description requires agent to produce activity_refs on each proposition."""
    from agents.value_design.value_proposition_generator import create_value_proposition_generator_task
    agent = MagicMock()
    with patch("agents.value_design.value_proposition_generator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_value_proposition_generator_task(agent=agent)
    _, kwargs = MockTask.call_args
    assert "activity_refs" in kwargs["description"]


def test_task_description_includes_beneficiaries():
    """Task description requires agent to produce beneficiaries on each proposition."""
    from agents.value_design.value_proposition_generator import create_value_proposition_generator_task
    agent = MagicMock()
    with patch("agents.value_design.value_proposition_generator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_value_proposition_generator_task(agent=agent)
    _, kwargs = MockTask.call_args
    assert "beneficiaries" in kwargs["description"]


def test_task_description_reads_activity_insights_opportunistically():
    """Task description reads activity_insights and handles missing data gracefully."""
    from agents.value_design.value_proposition_generator import create_value_proposition_generator_task
    agent = MagicMock()
    with patch("agents.value_design.value_proposition_generator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_value_proposition_generator_task(agent=agent)
    _, kwargs = MockTask.call_args
    assert "activity_insights" in kwargs["description"]
    # Must instruct agent to skip if absent (Error: prefix)
    assert "Error:" in kwargs["description"]


def test_task_description_lists_valid_benefit_types():
    """Task description enumerates the valid benefit_types."""
    from agents.value_design.value_proposition_generator import create_value_proposition_generator_task
    agent = MagicMock()
    with patch("agents.value_design.value_proposition_generator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_value_proposition_generator_task(agent=agent)
    _, kwargs = MockTask.call_args
    for bt in ("time_saving", "cost_reduction", "quality_improvement", "risk_reduction", "experience"):
        assert bt in kwargs["description"], f"benefit_type '{bt}' missing from task description"
