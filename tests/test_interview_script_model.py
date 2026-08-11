# tests/test_interview_script_model.py
"""Scripts that can be cited.

`node_label` was the script's own title - "GS UK Internal Audit & Compliance Assessment
Interview" - so no script linked to a node, and question ids were section-relative `Q1.1`,
so all 17 L2 scripts emitted the same ones.
"""
import pytest

from api.services.interview_script_model import (
    LEVELS,
    RELATIONSHIPS,
    normalise_script_fields,
    normalise_scripts,
    question_id,
    validate_scripts,
    validate_scripts_against_registry,
)

REGISTRY = {"activities": [
    {"id": "0", "label": "SP-GS", "level": "L0", "active": True},
    {"id": "1", "label": "Property", "level": "L1", "active": True},
    {"id": "1.2", "label": "Planned Maintenance", "level": "L2", "active": True},
    {"id": "2", "label": "Fleet", "level": "L1", "active": True},
]}


def _script(script_id="SC-001", node_id="1.2", level="L2", relationship="internal",
            sections=None, perspective=None) -> dict:
    return {
        "script_id": script_id,
        "node_id": node_id,
        "level": level,
        "perspective": perspective,
        "relationship": relationship,
        "node_label": "Planned Maintenance L2 Interview",
        # Tags are required from the moment the vocabularies exist, so the default fixture
        # carries them - a fixture the write path would refuse proves nothing about it.
        "sections": sections if sections is not None else [
            {"section_id": "S1", "title": "Opening", "discipline": "governance",
             "question_intent": "evidence", "elicitation": "unprompted", "questions": [
                {"id": "Q1", "text": "..."}, {"id": "Q2", "text": "..."},
            ]},
        ],
    }


def _scripts(*items) -> dict:
    return {s["script_id"]: s for s in items}


def test_a_well_formed_set_raises_nothing():
    assert validate_scripts(_scripts(_script())) == []


def test_question_ids_are_unique_across_two_scripts_at_the_same_level():
    """The test the old scheme could not fail. The fixture held one script per level, so
    `Q1.1` never met another `Q1.1` - a property of the sample, not of the scheme. Two L2
    scripts is the smallest fixture that can discriminate."""
    a = _script(script_id="SC-001", node_id="1.2")
    b = _script(script_id="SC-002", node_id="2")
    ids = [question_id(s["script_id"], sec["section_id"], i)
           for s in (a, b) for sec in s["sections"] for i, _ in enumerate(sec["questions"], 1)]
    assert len(ids) == len(set(ids)) == 4


def test_a_question_id_carries_its_script_and_section():
    assert question_id("SC-014", "S3", 2) == "SC-014.S3.Q2"


def test_two_scripts_may_not_share_a_script_id():
    scripts = {"a": _script(script_id="SC-001"), "b": _script(script_id="SC-001")}
    problems = validate_scripts(scripts)
    assert any("SC-001" in p for p in problems)


def test_a_script_with_no_node_id_is_refused():
    s = _script()
    del s["node_id"]
    assert any("node_id" in p for p in validate_scripts(_scripts(s)))


def test_a_section_with_no_id_is_refused():
    """Some live sections carry section_id: null. A theme citing "S1: Strategic Mandate"
    cites a string Maya may rewrite on her next run."""
    s = _script(sections=[{"title": "Opening", "discipline": "governance",
                           "question_intent": "evidence", "elicitation": "unprompted",
                           "questions": [{"id": "Q1", "text": "x"}]}])
    assert any("section_id" in p for p in validate_scripts(_scripts(s)))


def test_two_sections_in_one_script_may_not_share_a_section_id():
    tagged = {"discipline": "governance", "question_intent": "evidence",
              "elicitation": "unprompted"}
    s = _script(sections=[
        {"section_id": "S1", "title": "A", **tagged, "questions": [{"id": "Q1", "text": "x"}]},
        {"section_id": "S1", "title": "B", **tagged, "questions": [{"id": "Q1", "text": "y"}]},
    ])
    assert any("S1" in p for p in validate_scripts(_scripts(s)))


@pytest.mark.parametrize("bad", ["employee", "INTERNAL", "", None])
def test_an_unknown_relationship_is_refused(bad):
    assert any("relationship" in p for p in validate_scripts(_scripts(_script(relationship=bad))))


def test_the_relationship_vocabulary_is_closed():
    assert RELATIONSHIPS == frozenset(
        {"internal", "customer", "regulator", "supplier", "partner"})


def test_every_tier_is_known():
    """`level` is the structural tier only now - the four role letters live in `perspective`."""
    assert LEVELS == frozenset({"L0", "L1", "L2", "L3"})


def test_a_script_anchored_to_an_unknown_node_is_refused():
    problems = validate_scripts_against_registry(_scripts(_script(node_id="9.9")), REGISTRY)
    assert any("9.9" in p for p in problems)


def test_an_external_script_anchors_to_the_entity():
    """A regulator regulates the entity and a customer of the entity may sit in another
    company - both are still about node 0, which is L0."""
    regulator = _script(script_id="SC-010", node_id="0", level="L0", perspective="A",
                         relationship="regulator")
    customer = _script(script_id="SC-011", node_id="0", level="L0", perspective="C",
                        relationship="customer")
    assert validate_scripts(_scripts(regulator, customer)) == []
    assert validate_scripts_against_registry(_scripts(regulator, customer), REGISTRY) == []


@pytest.mark.parametrize("bad", ["x", "role", ""])
def test_an_unknown_perspective_is_refused(bad):
    problems = validate_scripts(_scripts(_script(perspective=bad)))
    assert any("perspective" in p for p in problems)


def test_a_null_perspective_is_the_default_and_is_free():
    assert validate_scripts(_scripts(_script(perspective=None))) == []


def test_a_role_script_may_omit_the_tier():
    """A script normalised from one written before the split carries perspective with no
    tier at all - the tier was never recorded for it, and refusing it invents a defect
    that is really just missing history."""
    s = _script(level=None, perspective="F")
    assert validate_scripts(_scripts(s)) == []


def test_a_non_role_script_must_still_carry_a_real_tier():
    """Only a role script's tier is allowed to be missing. An ordinary script with no
    perspective and no valid level is still refused."""
    problems = validate_scripts(_scripts(_script(level=None, perspective=None)))
    assert any("level" in p for p in problems)


def test_a_role_script_with_an_invalid_non_null_tier_is_refused():
    problems = validate_scripts(_scripts(_script(level="not-a-tier", perspective="F")))
    assert any("level" in p for p in problems)


def test_normalise_reads_a_pre_split_role_letter_as_level_null_perspective_set():
    """Scripts written before the split filed the role letter straight into `level`, with
    no `perspective` key at all - exactly what the sixteen scripts on the live project
    carry today."""
    legacy = {"script_id": "SC-014", "node_id": "1.F", "level": "F"}
    normalised = normalise_script_fields(legacy)
    assert normalised["level"] is None
    assert normalised["perspective"] == "F"


def test_normalise_leaves_an_already_split_script_alone():
    modern = _script(level="L1", perspective="F")
    assert normalise_script_fields(modern) == modern


def test_normalise_leaves_an_ordinary_script_alone():
    ordinary = _script(level="L2", perspective=None)
    assert normalise_script_fields(ordinary) == ordinary


def test_normalise_scripts_applies_across_the_whole_map():
    scripts = {
        "SC-014": {"script_id": "SC-014", "node_id": "1.F", "level": "F"},
        "SC-015": {"script_id": "SC-015", "node_id": "1.2", "level": "L2"},
    }
    normalised = normalise_scripts(scripts)
    assert normalised["SC-014"]["level"] is None
    assert normalised["SC-014"]["perspective"] == "F"
    assert normalised["SC-015"]["level"] == "L2"
    assert normalised["SC-015"].get("perspective") is None


def test_a_legacy_script_survives_normalisation_and_validation_together():
    """The actual write-path sequence: a script written before the split is normalised,
    then validated as part of a merged batch, and must not be refused."""
    legacy = {"script_id": "SC-014", "node_id": "1.F", "level": "F",
              "relationship": "internal", "node_label": "Frontline",
              "sections": []}
    normalised = normalise_scripts({"SC-014": legacy})
    assert validate_scripts(normalised) == []


def test_an_empty_registry_blocks_nothing():
    # A first run has no registry, and refusing every script then would block the pipeline.
    assert validate_scripts_against_registry(_scripts(_script(node_id="9.9")), {}) == []


def test_a_script_id_may_not_move_to_another_node():
    """The registry says SC-005 is node 1.2. A batch filing it against 2.7 must be refused.

    The rule this once shared with validate_script_registry_succession (deleted with the
    retired interview_script_registry door - code review round 1, Important 2 of the
    script-ledger-as-a-table Task 3 report: it had no production caller left once that door
    closed, and the redefine/drop guarantee it stated now holds structurally in
    register_scripts_sync instead - ON CONFLICT(script_id) DO NOTHING never moves node_id,
    and nothing anywhere issues a DELETE) is enforced here on the door that actually carries
    the scripts. Without this check the batch would land and the merge, which keys on
    script_id, would overwrite 1.2's script with 2.7's content.
    """
    from api.services.interview_script_model import validate_scripts_against_script_registry
    registry = {"scripts": [{"id": "SC-005", "node_id": "1.2", "active": True}]}
    scripts = {"SC-005": {"script_id": "SC-005", "node_id": "2.7"}}
    problems = validate_scripts_against_script_registry(scripts, registry)
    assert len(problems) == 1
    assert "SC-005" in problems[0] and "1.2" in problems[0] and "2.7" in problems[0]


def test_an_unregistered_script_id_is_free():
    """Growth is free. A new id is how every script starts."""
    from api.services.interview_script_model import validate_scripts_against_script_registry
    registry = {"scripts": [{"id": "SC-005", "node_id": "1.2", "active": True}]}
    scripts = {"SC-090": {"script_id": "SC-090", "node_id": "3.4"}}
    assert validate_scripts_against_script_registry(scripts, registry) == []


def test_a_registered_id_kept_on_its_own_node_is_free():
    """Re-emitting a script for the node it already serves is a revision, not a move."""
    from api.services.interview_script_model import validate_scripts_against_script_registry
    registry = {"scripts": [{"id": "SC-005", "node_id": "1.2", "active": True}]}
    scripts = {"SC-005": {"script_id": "SC-005", "node_id": "1.2"}}
    assert validate_scripts_against_script_registry(scripts, registry) == []


def test_an_empty_script_registry_accepts_anything():
    """A first run has no registry, and must not be blocked by one it has not written yet."""
    from api.services.interview_script_model import validate_scripts_against_script_registry
    scripts = {"SC-001": {"script_id": "SC-001", "node_id": "0"}}
    assert validate_scripts_against_script_registry(scripts, {}) == []
