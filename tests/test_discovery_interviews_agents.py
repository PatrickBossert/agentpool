"""Unit tests for the three discovery interview agent modules."""
from unittest.mock import MagicMock, patch
import pytest


def _mock_agent():
    return MagicMock()


# ── Interview Coordinator ─────────────────────────────────────────────────────

def test_interview_coordinator_task_includes_assignments():
    """Task description includes the stakeholder assignments block when provided."""
    from agents.discovery.interview_coordinator import create_interview_coordinator_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(
            agent=agent,
            stakeholder_assignments="- Alice Chen (Head of Ops) → L2: Order Fulfilment",
        )
    _, kwargs = MockTask.call_args
    assert "Alice Chen" in kwargs["description"]
    assert "interview_plan" in kwargs["description"]


def test_coordinator_task_reads_interview_scripts():
    """Task description instructs agent to read interview_scripts (not value_chain_tree)."""
    from agents.discovery.interview_coordinator import create_interview_coordinator_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(agent=agent, stakeholder_assignments="")
    _, kwargs = MockTask.call_args
    assert "interview_scripts" in kwargs["description"]
    assert "value_chain_tree" not in kwargs["description"]


def test_coordinator_task_writes_interview_plan():
    """Task description instructs agent to write interview_plan."""
    from agents.discovery.interview_coordinator import create_interview_coordinator_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(agent=agent, stakeholder_assignments="")
    _, kwargs = MockTask.call_args
    assert "interview_plan" in kwargs["description"]


def test_coordinator_task_asks_for_the_script_id_in_every_plan_entry():
    """The plan is where script_id enters the system, so the prompt is where it is asked for.

    Deliberately a weak assertion about a prompt rather than a strong one about behaviour -
    what actually guarantees a stored script_id is InterviewSessionTool._create, which
    resolves an omitted id from the label itself (tests/test_session_script_citation.py).
    This only holds the near end of the plumbing: the coordinator's example session entry
    used to show stakeholder_id, name, node_label, and voice_config, and an entry the
    example does not contain is one the model has no reason to emit.
    """
    from agents.discovery.interview_coordinator import create_interview_coordinator_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(agent=agent, stakeholder_assignments="")
    _, kwargs = MockTask.call_args
    assert '"script_id"' in kwargs["description"], (
        "the session entry example must carry script_id, not just prose about it"
    )


def test_coordinator_task_injects_assignments():
    """Task description includes injected stakeholder assignment data."""
    from agents.discovery.interview_coordinator import create_interview_coordinator_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(
            agent=agent,
            stakeholder_assignments="- Bob Smith → L3: Packing",
        )
    _, kwargs = MockTask.call_args
    assert "Bob Smith" in kwargs["description"]


def test_coordinator_task_includes_voice_locale_table():
    """Task description contains the voice locale lookup table."""
    from agents.discovery.interview_coordinator import create_interview_coordinator_task
    agent = _mock_agent()
    with patch("agents.discovery.interview_coordinator.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_interview_coordinator_task(agent=agent, stakeholder_assignments="")
    _, kwargs = MockTask.call_args
    assert "elevenlabs_voice_id" in kwargs["description"]
    assert "voice_config" in kwargs["description"]


# ── Stakeholder Interviewer ───────────────────────────────────────────────────

def test_stakeholder_interviewer_task_reads_interview_plan():
    """Task description instructs agent to read interview_plan."""
    from agents.discovery.stakeholder_interviewer import create_stakeholder_interviewer_task
    agent = _mock_agent()
    with patch("agents.discovery.stakeholder_interviewer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_stakeholder_interviewer_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "interview_plan" in kwargs["description"]
    assert "interview_transcripts" in kwargs["description"]


def test_interviewer_task_creates_sessions():
    """Task description instructs agent to use InterviewSessionTool with operation='create'."""
    from agents.discovery.stakeholder_interviewer import create_stakeholder_interviewer_task
    agent = _mock_agent()
    with patch("agents.discovery.stakeholder_interviewer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_stakeholder_interviewer_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "InterviewSessionTool" in kwargs["description"]
    assert "create" in kwargs["description"]


def test_interviewer_task_reads_interview_plan():
    """Task description reads interview_plan from SQLiteStateTool."""
    from agents.discovery.stakeholder_interviewer import create_stakeholder_interviewer_task
    agent = _mock_agent()
    with patch("agents.discovery.stakeholder_interviewer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_stakeholder_interviewer_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "interview_plan" in kwargs["description"]


def test_interviewer_task_writes_interview_transcripts():
    """Task description writes interview_transcripts via SQLiteStateTool."""
    from agents.discovery.stakeholder_interviewer import create_stakeholder_interviewer_task
    agent = _mock_agent()
    with patch("agents.discovery.stakeholder_interviewer.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_stakeholder_interviewer_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "interview_transcripts" in kwargs["description"]


# ── Synthesis Analyst ─────────────────────────────────────────────────────────

def test_synthesis_analyst_task_writes_all_three_keys():
    """Task description instructs agent to write activity_insights, requirements, themes.

    `value_levers` was the third until the crews were re-sequenced. Morgan writes those and
    now runs first, so a write here would land on top of the levers Maya designed the
    instruments against and a reviewer approved.
    """
    from agents.discovery.synthesis_analyst import create_synthesis_analyst_task
    agent = _mock_agent()
    with patch("agents.discovery.synthesis_analyst.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_synthesis_analyst_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    for key in ("activity_insights", "requirements", "themes"):
        assert key in kwargs["description"], f"Key '{key}' missing from task description"
    assert "value_levers" not in kwargs["description"]


def test_synthesis_analyst_task_reads_the_answer_store():
    """He reads answers, not the transcript blob.

    This asserted on `interview_transcripts` until answers became addressable. A blob cannot
    be filtered by discipline or by who the speaker is to this organisation, and the corpus
    is too large to read whole - both of which are the point of the tagged store.
    """
    from agents.discovery.synthesis_analyst import create_synthesis_analyst_task
    agent = _mock_agent()
    with patch("agents.discovery.synthesis_analyst.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_synthesis_analyst_task(agent=agent, context_tasks=[])
    _, kwargs = MockTask.call_args
    assert "collection='interviews'" in kwargs["description"]
    assert "interview_transcripts" not in kwargs["description"]
