# tests/test_staleness.py
"""Stale means: an input this was built from has been approved again since.

Pure, so the rule can be tested without a database and cannot quietly depend on one.
"""
from api.services.lineage_service import staleness

MODEL_V8 = {"id": 1, "output_type": "value_chain_model", "version": 8, "input_output_ids": [],
            "document_ids": []}
MODEL_V9 = {"id": 2, "output_type": "value_chain_model", "version": 9, "input_output_ids": [],
            "document_ids": []}
SCRIPTS = {"id": 3, "output_type": "interview_scripts", "version": 5,
           "input_output_ids": [1], "document_ids": []}
LEVERS = {"id": 4, "output_type": "value_levers", "version": 2,
          "input_output_ids": [], "document_ids": [3]}


def test_built_from_the_latest_approved_input_is_fresh():
    result = staleness([MODEL_V8, SCRIPTS], approvals={"value_chain_model": 8})
    assert result[3]["state"] == "fresh"


def test_a_newer_approved_input_makes_it_stale():
    result = staleness([MODEL_V8, MODEL_V9, SCRIPTS], approvals={"value_chain_model": 9})
    assert result[3]["state"] == "stale"
    assert result[3]["behind"] == [
        {"output_type": "value_chain_model", "built_from": 8, "approved": 9}
    ]


def test_a_newer_but_unapproved_input_does_not():
    """Alex wrote tree v7, v8 and v9 inside ninety seconds. Those are working state, and
    flagging each would make downstream work flash stale three times in one run."""
    result = staleness([MODEL_V8, MODEL_V9, SCRIPTS], approvals={"value_chain_model": 8})
    assert result[3]["state"] == "fresh"


def test_an_output_with_no_ancestry_is_unknown_not_fresh():
    """Morgan's levers have document ancestry and no state ancestry, and every output written
    before lineage existed has neither. Calling those fresh would assert something nothing
    knows."""
    result = staleness([LEVERS], approvals={})
    assert result[4]["state"] == "unknown"


def test_staleness_is_reported_for_every_stale_input_not_just_the_first():
    two_inputs = {**SCRIPTS, "input_output_ids": [1, 5]}
    other = {"id": 5, "output_type": "value_levers", "version": 1,
             "input_output_ids": [], "document_ids": []}
    result = staleness(
        [MODEL_V8, other, two_inputs],
        approvals={"value_chain_model": 9, "value_levers": 3},
    )
    assert len(result[3]["behind"]) == 2
