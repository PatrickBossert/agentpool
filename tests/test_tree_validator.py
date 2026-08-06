"""Structural checks on value_chain_tree.

The regression these exist for: a node reaches the registry only if it is in the tree, and
no registry written by value_chain_mapper has ever held an L0. Trees v10 and v12 - written
on 6 August, with the root instruction in Alex's prompt since 4 August - are both a bare
list of L1 entities.
"""
from api.services.tree_validation import validate_tree_structure

GOOD_TREE = [
    {"id": "0", "label": "GS-UK", "level": "L0", "children": [
        {"id": "0.A", "label": "Audit", "level": "L0"},
        {"id": "0.S", "label": "Corporate Services frontline", "level": "L0"},
        {"id": "1", "label": "Property", "level": "L1", "children": [
            {"id": "1.C", "label": "Property customer", "level": "L1"},
            {"id": "1.F", "label": "Property frontline", "level": "L1"},
            {"id": "1.1", "label": "Strategic Planning", "level": "L2", "children": [
                {"id": "1.1.1", "label": "Asset Hierarchy", "level": "L3"},
            ]},
        ]},
    ]},
]

PREV = {"activities": [
    {"id": "0", "label": "GS-UK", "level": "L0", "active": True},
    {"id": "0.A", "label": "Audit", "level": "L0", "active": True},
    {"id": "0.S", "label": "Corporate Services frontline", "level": "L0", "active": True},
    {"id": "1", "label": "Property", "level": "L1", "active": True},
    {"id": "1.C", "label": "Property customer", "level": "L1", "active": True},
    {"id": "1.F", "label": "Property frontline", "level": "L1", "active": True},
    {"id": "1.1", "label": "Strategic Planning", "level": "L2", "active": True},
    {"id": "1.1.1", "label": "Asset Hierarchy", "level": "L3", "active": True},
]}


def _codes(warnings):
    return sorted(w["code"] for w in warnings)


def test_a_correct_tree_is_silent():
    assert validate_tree_structure(GOOD_TREE, PREV) == []


def test_a_rootless_tree_raises_missing_l0():
    rootless = GOOD_TREE[0]["children"][2:]   # the bare L1 list Alex actually produces
    assert "missing_l0" in _codes(validate_tree_structure(rootless, PREV))


def test_a_root_at_the_wrong_level_raises_missing_l0():
    wrong = [{"id": "0", "label": "GS-UK", "level": "L1", "children": []}]
    assert "missing_l0" in _codes(validate_tree_structure(wrong, None))


def test_an_l1_outside_the_root_raises_missing_l0():
    detached = list(GOOD_TREE) + [{"id": "9", "label": "Orphan", "level": "L1"}]
    warnings = validate_tree_structure(detached, PREV)
    assert "missing_l0" in _codes(warnings)
    assert any("9" in w["detail"] for w in warnings)


def test_a_dropped_role_node_raises_missing_role_node():
    import copy
    tree = copy.deepcopy(GOOD_TREE)
    prop = tree[0]["children"][2]
    prop["children"] = [c for c in prop["children"] if c["id"] != "1.F"]
    warnings = validate_tree_structure(tree, PREV)
    assert "missing_role_node" in _codes(warnings)
    assert any(w["subject"] == "1.F" for w in warnings)


def test_a_redefined_id_raises_id_redefined():
    import copy
    tree = copy.deepcopy(GOOD_TREE)
    tree[0]["children"][2]["label"] = "Something Else Entirely"
    warnings = validate_tree_structure(tree, PREV)
    assert "id_redefined" in _codes(warnings)
    assert any(w["subject"] == "1" for w in warnings)


def test_first_run_checks_only_the_root():
    """No previous registry means no baseline. Stated explicitly because a validator that
    passes silently when it has nothing to compare against looks identical to a broken
    one."""
    assert validate_tree_structure(GOOD_TREE, None) == []
    rootless = GOOD_TREE[0]["children"][2:]
    assert _codes(validate_tree_structure(rootless, None)) == ["missing_l0"]


def test_a_retired_node_is_not_a_redefinition():
    """The ledger may grow and may retire; only redefining is a finding."""
    import copy
    tree = copy.deepcopy(GOOD_TREE)
    prop = tree[0]["children"][2]
    prop["children"] = [c for c in prop["children"] if c["id"] != "1.1"]
    assert "id_redefined" not in _codes(validate_tree_structure(tree, PREV))


def test_an_already_inactive_role_node_is_not_reported_missing():
    import copy
    prev = copy.deepcopy(PREV)
    next(a for a in prev["activities"] if a["id"] == "1.F")["active"] = False
    tree = copy.deepcopy(GOOD_TREE)
    prop = tree[0]["children"][2]
    prop["children"] = [c for c in prop["children"] if c["id"] != "1.F"]
    assert "missing_role_node" not in _codes(validate_tree_structure(tree, prev))


def test_a_tree_that_is_not_a_list_is_reported_not_crashed():
    warnings = validate_tree_structure({"id": "0"}, PREV)
    assert _codes(warnings) == ["missing_l0"]
    assert "dict" in warnings[0]["detail"]
