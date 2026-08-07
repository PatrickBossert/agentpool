"""Where Casey's themes anchor.

The distribution check is the one that matters. A per-theme mismatch is an individual
mistake; a skew is the signature of the bias the whole L0 design exists to remove, and when
it happens no individual theme looks wrong. Per-item validation cannot catch an emergent
property.
"""
from api.services.anchor_validation import (
    validate_theme_anchors, L3_SKEW_THRESHOLD, L3_SKEW_MIN_THEMES, SKEW_RERAISE_DELTA,
)

REGISTRY = {"activities": (
    [{"id": "0", "level": "L0", "active": True},
     {"id": "0.A", "level": "L0", "active": True},
     {"id": "1", "level": "L1", "active": True},
     {"id": "1.F", "level": "L1", "active": True}]
    + [{"id": f"1.{n}", "level": "L2", "active": True} for n in range(1, 6)]
    + [{"id": f"1.{n}.1", "level": "L3", "active": True} for n in range(1, 6)]
)}


def _codes(ws):
    return sorted(w["code"] for w in ws)


def _theme(tid, kind, anchors, name="t"):
    return {"id": tid, "kind": kind, "theme": name, "description": "d", "anchors": anchors}


def test_a_vertical_theme_below_l1_is_a_mismatch():
    ws = validate_theme_anchors([_theme("TH-01", "vertical", ["1.1.1"])], REGISTRY)
    assert "anchor_level_mismatch" in _codes(ws)
    assert ws[0]["subject"] == "TH-01"


def test_a_vertical_theme_at_l0_is_fine():
    assert validate_theme_anchors([_theme("TH-01", "vertical", ["0"])], REGISTRY) == []


def test_a_governance_theme_at_l3_is_a_mismatch():
    ws = validate_theme_anchors(
        [_theme("TH-01", "horizontal", ["1.2.1"], name="Data governance and assurance")],
        REGISTRY)
    assert "anchor_level_mismatch" in _codes(ws)


def test_the_distribution_check_fires_where_per_item_checks_cannot():
    """Eight of ten themes anchor only at L3 and every one is individually defensible.
    No per-theme rule can see this; only the population can."""
    themes = [_theme(f"TH-{i:02d}", "horizontal", [f"1.{(i % 5) + 1}.1"]) for i in range(8)]
    themes += [_theme("TH-09", "horizontal", ["1.2"]), _theme("TH-10", "vertical", ["0"])]
    ws = validate_theme_anchors(themes, REGISTRY)
    assert _codes(ws) == ["l3_skew"], "no individual theme should be flagged"
    assert ws[0]["measure"] == 0.8
    assert ws[0]["subject"] is None


def test_the_minimum_count_guard_suppresses_skew():
    """Four all-L3 themes are a small tactical engagement, not a skew."""
    themes = [_theme(f"TH-{i:02d}", "horizontal", [f"1.{i + 1}.1"]) for i in range(4)]
    assert len(themes) < L3_SKEW_MIN_THEMES
    assert "l3_skew" not in _codes(validate_theme_anchors(themes, REGISTRY))


def test_a_balanced_set_is_silent():
    themes = [
        _theme("TH-01", "vertical", ["0"]),
        _theme("TH-02", "horizontal", ["1"]),
        _theme("TH-03", "horizontal", ["1.2"]),
        _theme("TH-04", "horizontal", ["1.3.1"]),
        _theme("TH-05", "horizontal", ["1.F"]),
    ]
    assert validate_theme_anchors(themes, REGISTRY) == []


def test_a_theme_anchored_to_a_node_that_does_not_exist():
    ws = validate_theme_anchors([_theme("TH-01", "horizontal", ["9.9.9"])], REGISTRY)
    assert "unknown_anchor" in _codes(ws)


def test_a_theme_anchored_at_both_l3_and_above_does_not_count_as_l3_only():
    themes = [_theme(f"TH-{i:02d}", "horizontal", [f"1.{i + 1}.1", "1"]) for i in range(6)]
    assert "l3_skew" not in _codes(validate_theme_anchors(themes, REGISTRY))


def test_an_empty_registry_accepts_anything():
    """A project with no value chain yet must not be blocked."""
    themes = [_theme(f"TH-{i:02d}", "horizontal", ["9.9.9"]) for i in range(6)]
    assert validate_theme_anchors(themes, {"activities": []}) == []


def test_exactly_at_the_threshold_does_not_fire():
    """Seven of ten is 0.70, and the rule is 'more than' - stated so the boundary is a
    decision rather than an accident of the comparison operator."""
    themes = [_theme(f"TH-{i:02d}", "horizontal", [f"1.{(i % 5) + 1}.1"]) for i in range(7)]
    themes += [_theme(f"TH-1{i}", "horizontal", ["1.2"]) for i in range(3)]
    ws = validate_theme_anchors(themes, REGISTRY)
    assert "l3_skew" not in _codes(ws), f"0.70 is not more than {L3_SKEW_THRESHOLD}"


def test_the_thresholds_are_single_named_constants():
    assert L3_SKEW_THRESHOLD == 0.70
    assert L3_SKEW_MIN_THEMES == 5
    assert SKEW_RERAISE_DELTA == 0.10
