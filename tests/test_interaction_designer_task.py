# tests/test_interaction_designer_task.py
"""Maya Patel designs assessment instruments. She does not write interview findings.

Her task previously told her to produce seven *_interview_summaries.json artefacts
containing strategic_intent, current_maturity, key_decision_quality_gaps, quick_wins
and so on. That is synthesis of interview results - Casey Liu's job - and Maya was
producing it before any interview had been conducted, so the content was invented
rather than observed.

The in-interview `synthesis_check` is a different thing and stays hers: it is the
reflective summary the interviewer offers the interviewee for correction.

The instruction to fan output across those keys turned out to live in
`expected_output`, not in the numbered steps of `description` - so a test that only
inspected `.description` could not have caught it. Run 30 made three refused writes
at the end (l0_interview_summaries, interview_summaries, and audit_interview_summaries)
even though `.description` never mentioned them; the LLM read the promise in
`expected_output` and tried to keep it. Tests here check both fields.

Her task also never read what already exists before generating, so a re-run
regenerated the whole set from the registry as though starting fresh - wasteful, and
it churns script text a consultant may have edited by hand. She now reads
`interview_scripts` and `interview_script_registry` first and generates only for
activities that do not have a script yet.
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
def mock_llm():
    return MagicMock(spec=LLM)


@pytest.fixture
def task(mock_llm):
    agent = create_interaction_designer(slug="t", llm=mock_llm, tools=[])
    return create_interaction_designer_task(agent=agent, client_name="Test Client")


@pytest.fixture
def task_description(task):
    return task.description


@pytest.mark.parametrize("artefact", SUMMARY_ARTEFACTS)
def test_task_does_not_ask_maya_to_write_interview_summaries(task, artefact):
    """Checked against both fields the agent is given: the instruction lived in
    expected_output, not description, so a description-only check could not fail
    on the live defect."""
    assert artefact not in task.description, (
        f"Maya is still instructed to produce {artefact} - that is Casey Liu's output"
    )
    assert artefact not in task.expected_output, (
        f"Maya is still promised to deliver {artefact} in expected_output - "
        "that is Casey Liu's output, and the promise is what drove the refused writes"
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


def test_maya_reads_what_exists_before_generating(task_description):
    """A re-run must add the missing nodes, not regenerate the set.

    A moved script id is refused at write time, but a blind re-run would still
    rewrite every existing script, churning text a human may have edited.
    Checked against the read form specifically (`operation='read'`), not merely
    `key='interview_scripts'` anywhere in the text - that weaker check is already satisfied by
    the pre-existing write instruction further down and would not have caught the original
    defect.
    """
    assert "operation='read', key='interview_scripts'" in task_description, (
        "must read the existing scripts"
    )
    assert "operation='read', key='interview_script_registry'" in task_description, (
        "must read the script ledger"
    )
    lowered = task_description.lower()
    assert "only" in lowered and "missing" in lowered, "must say to generate only what is missing"


@pytest.mark.parametrize("sampling_phrase", [
    "do not write one script per node",
    "not every l3",
    "node you have chosen",
    "why that node was chosen",
    "a script for every l3 activity",
])
def test_maya_is_not_told_to_sample_the_nodes(task, sampling_phrase):
    """The contract is one script per active node, so the sampling rule must be gone.

    This asserts the ABSENCE of the contradicting instruction rather than the presence
    of the new one, because presence could not fail. The predecessor of this test looked
    for "every active", which step 1 has said since before this contract existed - while
    the write instruction 700 lines below it still opened "Do not write one script per
    node" and told her to select among L2 and L3. The prompt stated both contracts at
    once, the validator implemented only one of them, and the test saw only the agreeable
    half: it passed against the prompt that produced sixteen scripts for eighty-six nodes.
    """
    assert sampling_phrase not in task.description.lower(), (
        f"the sampling rule survives in the task description: {sampling_phrase!r}. "
        "It contradicts the one-script-per-active-node contract the coverage validator "
        "warns against, so the re-run loop never converges and the warning never clears"
    )


def test_expected_output_promises_a_script_for_every_node(task):
    """expected_output is an instruction too - the summary artefacts got written because
    it promised them - so the contract has to hold there as well as in the steps."""
    assert "selected" not in task.expected_output.lower(), (
        "expected_output still promises scripts for 'selected' L2 and L3 nodes"
    )
    assert "every active node" in task.expected_output.lower()


def test_maya_is_told_the_contract_is_every_node(task_description):
    """Sixteen was defensible because no target was stated. State it, at the point of
    writing - step 1 already said it and the write instruction disagreed."""
    assert "one interview script per active node" in task_description.lower()


def test_maya_is_not_told_to_write_undeclared_keys(task):
    """Run 30 made three refused writes at the end - l0_interview_summaries,
    interview_summaries, and audit_interview_summaries - so the instruction to fan output
    across keys survived the ownership guard that now refuses it. That instruction lived in
    expected_output, so both fields are checked here."""
    assert "_interview_summaries" not in task.description
    assert "interview_summaries" not in task.description
    assert "_interview_summaries" not in task.expected_output
    assert "interview_summaries" not in task.expected_output
