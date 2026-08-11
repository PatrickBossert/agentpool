"""A script's level must match the level of the node it anchors to.

validate_scripts_against_registry proves the node exists. Nothing proved it was the right
kind of node, which is how run 26 filed an L0 board interview against node "1" - Property
Asset Management, an L1 entity - beside the L1 script that legitimately owns it. Registry
v5 had no "0" to anchor to, so Maya picked a node that did exist and the validator accepted
it.
"""
from api.services.interview_script_model import validate_anchor_levels

REGISTRY = {"activities": [
    {"id": "0", "level": "L0", "active": True},
    {"id": "0.A", "level": "L0", "active": True},
    {"id": "0.S", "level": "L0", "active": True},
    {"id": "1", "level": "L1", "active": True},
    {"id": "1.C", "level": "L1", "active": True},
    {"id": "1.F", "level": "L1", "active": True},
    {"id": "1.1", "level": "L2", "active": True},
    {"id": "1.1.1", "level": "L3", "active": True},
]}

LEGACY = {"activities": [
    {"id": "1", "level": "L1", "active": True},
    {"id": "1.1", "level": "L2", "active": True},
]}


def _s(level, node):
    return {"SC-001": {"script_id": "SC-001", "level": level, "node_id": node}}


def _ps(level, perspective, node):
    """A script written after the level/perspective split: the role lives in `perspective`,
    not `level`."""
    return {"SC-001": {"script_id": "SC-001", "level": level, "perspective": perspective,
                        "node_id": node}}


def test_the_run_26_defect_is_caught():
    problems = validate_anchor_levels(_s("L0", "1"), REGISTRY)
    assert len(problems) == 1
    assert "L0" in problems[0] and "'1'" in problems[0] and "L1" in problems[0]


def test_matching_levels_are_silent():
    for level, node in [("L0", "0"), ("L1", "1"), ("L2", "1.1"), ("L3", "1.1.1")]:
        assert validate_anchor_levels(_s(level, node), REGISTRY) == [], (level, node)


def test_a_role_script_must_anchor_to_its_own_role_node():
    assert validate_anchor_levels(_s("A", "0.A"), REGISTRY) == []
    assert validate_anchor_levels(_s("C", "1.C"), REGISTRY) == []
    assert validate_anchor_levels(_s("F", "1.F"), REGISTRY) == []
    assert validate_anchor_levels(_s("S", "0.S"), REGISTRY) == []
    problems = validate_anchor_levels(_s("A", "1.1"), REGISTRY)
    assert len(problems) == 1 and "0.A" in problems[0]


def test_a_new_format_role_script_must_anchor_to_its_own_role_node():
    """The same rule as test_a_role_script_must_anchor_to_its_own_role_node, but on a script
    shaped the way the split actually produces one: `level` holds the tier ('L1'/'L0'), and
    the role lives in `perspective`.

    Before the extension, this check only ever read `level`, and a new-format script's
    `level` is always a plain tier - never a role letter - so the check silently never fired
    for any script written after the split. A customer script misanchored to the plain chain
    "1" instead of its role node "1.C" is exactly what it would have let through.
    """
    assert validate_anchor_levels(_ps("L1", "C", "1.C"), REGISTRY) == []
    assert validate_anchor_levels(_ps("L1", "F", "1.F"), REGISTRY) == []
    assert validate_anchor_levels(_ps("L0", "A", "0.A"), REGISTRY) == []
    assert validate_anchor_levels(_ps("L0", "S", "0.S"), REGISTRY) == []
    problems = validate_anchor_levels(_ps("L1", "C", "1"), REGISTRY)
    assert len(problems) == 1 and "not a C role node" in problems[0]


def test_role_checks_are_skipped_when_the_registry_has_no_role_nodes():
    """A project whose value chain predates role nodes must not be blocked - the check
    activates when the nodes it judges against exist."""
    assert validate_anchor_levels(_s("A", "1.1"), LEGACY) == []
    assert validate_anchor_levels(_s("S", "1.1"), LEGACY) == []


def test_level_checks_still_apply_without_role_nodes():
    assert validate_anchor_levels(_s("L0", "1"), LEGACY) != []


def test_an_empty_registry_accepts_anything():
    assert validate_anchor_levels(_s("L0", "1"), {"activities": []}) == []


def test_an_unknown_anchor_is_left_to_the_existence_check():
    """Two validators, one message each - a missing node is reported once, not twice."""
    assert validate_anchor_levels(_s("L0", "9.9"), REGISTRY) == []
