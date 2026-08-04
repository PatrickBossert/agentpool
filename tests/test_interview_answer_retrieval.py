# tests/test_interview_answer_retrieval.py
"""What gets embedded, and what can be filtered before it ranks.

Exact grouping and coverage come from SQL; recall comes from Chroma. Counting how many
stakeholders mentioned something is a fact, and a vector search is the wrong instrument for
a fact.
"""
from unittest.mock import MagicMock, patch

from api.services.interview_answer_service import (
    answer_document,
    answer_metadata,
    index_answers,
)

ROW = {
    "id": 812, "question_text": "Is the asset record trusted?",
    "answer_text": "For compliance, yes. For investment, no.",
    "node_id": "1.2", "chain": "1", "level": "L2", "relationship": "internal",
    "discipline": "data", "question_intent": "evidence", "elicitation": "unprompted",
    "script_id": "SC-014", "section_id": "S3", "question_id": "SC-014.S3.Q1",
    "stakeholder_id": 7, "follow_up": 0, "node_label": "Planned Maintenance",
}


def test_the_document_carries_its_own_frame():
    """A semantic hit arrives as a sentence with no context otherwise, and a reader cannot
    tell whose answer it was or what it was about."""
    doc = answer_document(ROW)
    assert "Planned Maintenance" in doc
    assert "1.2" in doc
    assert "data" in doc
    assert ROW["question_text"] in doc
    assert ROW["answer_text"] in doc


def test_the_metadata_carries_every_filterable_tag():
    """"Answers about data from customers of the Fleet chain" must be a filtered query rather
    than a hope about embedding similarity."""
    meta = answer_metadata(ROW)
    for field in ("node_id", "chain", "level", "relationship", "discipline",
                  "question_intent", "elicitation", "stakeholder_id", "answer_id"):
        assert field in meta, f"{field} missing - it cannot be filtered on"
    assert meta["answer_id"] == 812


def test_metadata_values_are_chroma_scalars():
    """Chroma rejects None and nested values. Every entity-anchored answer has a null chain,
    so this would fail the upsert for the whole A, C, and S programme."""
    meta = answer_metadata({**ROW, "chain": None})
    assert all(isinstance(v, (str, int, float, bool)) for v in meta.values())
    assert meta["chain"] == ""


def test_indexing_upserts_one_document_per_answer():
    collection = MagicMock()
    client = MagicMock()
    client.get_or_create_collection.return_value = collection

    with patch("api.services.interview_answer_service.get_chroma_client", return_value=client):
        indexed = index_answers("acme", [ROW, {**ROW, "id": 813}])

    assert indexed == 2
    client.get_or_create_collection.assert_called_once_with(name="acme_interviews")
    _, kwargs = collection.upsert.call_args
    assert kwargs["ids"] == ["812", "813"]
    assert len(kwargs["documents"]) == 2
    assert len(kwargs["metadatas"]) == 2


def test_a_chroma_outage_does_not_lose_the_session():
    """The SQLite rows are the system of record and can be re-indexed at any time. Raising
    here would cost an interview a person has already given."""
    with patch("api.services.interview_answer_service.get_chroma_client",
               side_effect=RuntimeError("chroma is down")):
        assert index_answers("acme", [ROW]) == 0


def test_indexing_nothing_touches_no_client():
    # A session that resolved no script writes no rows; opening a connection to index an
    # empty list would fail the whole completion on an outage that changes nothing.
    with patch("api.services.interview_answer_service.get_chroma_client") as client:
        assert index_answers("acme", []) == 0
    client.assert_not_called()
