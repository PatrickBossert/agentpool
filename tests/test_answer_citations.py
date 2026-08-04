# tests/test_answer_citations.py
"""Themes cite answers, not prose.

A theme citing a stakeholder name and a node label cites two strings that may both be
rewritten. An answer id resolves to exactly one answer, in one session, on one node, and the
rows are append-only.
"""
from unittest.mock import MagicMock, patch


def _task() -> str:
    from agents.discovery.synthesis_analyst import create_synthesis_analyst_task
    with patch("agents.discovery.synthesis_analyst.Task") as MockTask:
        MockTask.return_value = MagicMock()
        create_synthesis_analyst_task(agent=MagicMock(), context_tasks=[])
    _, kwargs = MockTask.call_args
    return kwargs["description"]


def test_casey_reads_the_answer_store_rather_than_transcript_blobs():
    """The corpus is too large to read whole, and a blob cannot be filtered by discipline."""
    assert "collection='interviews'" in _task()


def test_a_theme_cites_answer_ids():
    """Asserted on the schema, not on the word appearing anywhere.

    The prose beside it also says "answer_id", so a bare substring check passed with the
    field removed from the evidence object entirely - which is the only place it does
    anything.
    """
    description = _task()
    assert '"evidence": [{"answer_id"' in description
    # The strings that get rewritten, gone from the evidence object rather than merely
    # joined by the id: a citation that carries both invites the reader to trust the label.
    assert '"node_label"' not in description.split('"evidence"')[1][:200]


def test_a_theme_still_requires_two_distinct_stakeholders():
    # Preserved from before the citation change: one voice is an individual perspective.
    assert "two evidence entries from different stakeholders" in _task()


def test_a_strategic_requirement_still_names_the_themes_it_derives_from():
    assert "from_themes" in _task()


def test_casey_weights_unprompted_evidence():
    """Six stakeholders raising data quality means something entirely different if five were
    handed the phrase - the tag exists so he does not have to infer it."""
    assert "unprompted" in _task()


def test_casey_holds_the_chroma_tool_that_reads_them():
    """Instructing him to query a collection he has no tool for would fail at run time, in a
    place nobody is watching."""
    from agents.tools.registry import get_tools_for_agent
    names = {type(t).__name__ for t in get_tools_for_agent(
        "synthesis_analyst", slug="x", run_id=1, sector="utilities")}
    assert "ChromaQueryTool" in names
