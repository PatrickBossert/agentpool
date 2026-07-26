# tests/test_interaction_designer_task.py
"""Maya Patel designs assessment instruments. She does not write interview findings.

Her task previously told her to produce seven *_interview_summaries.json artefacts
containing strategic_intent, current_maturity, key_decision_quality_gaps, quick_wins
and so on. That is synthesis of interview results - Casey Liu's job - and Maya was
producing it before any interview had been conducted, so the content was invented
rather than observed.

The in-interview `synthesis_check` is a different thing and stays hers: it is the
reflective summary the interviewer offers the interviewee for correction.
"""
from unittest.mock import MagicMock

import pytest
from crewai import LLM

from agents.discovery.interaction_designer import (
    create_interaction_designer,
    create_interaction_designer_task,
)

SUMMARY_ARTEFACTS = [
    "l0_interview_summaries",
    "l1_interview_summaries",
    "l2_interview_summaries",
    "audit_interview_summaries",
    "customer_interview_summaries",
    "frontline_interview_summaries",
    "corp_services_interview_summaries",
]


@pytest.fixture
def task_description():
    agent = create_interaction_designer(slug="t", llm=MagicMock(spec=LLM), tools=[])
    return create_interaction_designer_task(agent=agent, client_name="Test Client").description


@pytest.mark.parametrize("artefact", SUMMARY_ARTEFACTS)
def test_task_does_not_ask_maya_to_write_interview_summaries(task_description, artefact):
    assert artefact not in task_description, (
        f"Maya is still instructed to produce {artefact} - that is Casey Liu's output"
    )


def test_task_still_asks_maya_to_write_the_interview_scripts(task_description):
    """The removal must not take her actual deliverable with it."""
    assert "key='interview_scripts'" in task_description


def test_task_retains_the_in_interview_synthesis_check(task_description):
    """synthesis_check is part of an interview script, not a findings artefact."""
    assert "synthesis_check" in task_description


def test_task_still_covers_every_interview_category(task_description):
    """Scripts for L0-L3 plus customer, audit, frontline and corporate services."""
    for marker in ["L0", "L1", "L2", "L3", "customer interview", "audit interview",
                   "frontline worker interview", "corporate services interview"]:
        assert marker.lower() in task_description.lower(), f"lost coverage of {marker}"
