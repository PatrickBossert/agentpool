# tests/test_interview_scripts_service.py
"""Tests for the interview script index served to Maya Patel's Outputs panel.

Maya writes each batch of interview scripts to its own file, and a single file can
hold several interviews keyed by title. The raw output list therefore shows cryptic
file-derived types (interview_scripts_l2_1) rather than the thing a consultant
cares about: one interview per value chain stage, grouped by stakeholder category.
"""
import pytest

from api.services.interview_scripts_service import (
    dedupe_script_map,
    LEVEL_LABELS,
    LEVEL_ORDER,
    dedupe_and_order,
    flatten_script_file,
)


def _script(level, node, sections):
    return {
        "node_label": node,
        "level": level,
        "research_brief": "brief",
        "study_objectives": ["obj"],
        "sections": [{"title": f"S{i}", "target_minutes": 5,
                      "questions": [{"q": "a"}, {"q": "b"}]} for i in range(sections)],
    }


def test_flatten_extracts_one_entry_per_interview():
    """A file holding three interviews yields three entries, not one."""
    content = {
        "Customer Interview": _script("C", "SP Networks Operations", 8),
        "Audit Interview": _script("A", "Internal Audit", 10),
        "Frontline Interview": _script("F", "ISS FM Technician", 9),
    }
    entries = flatten_script_file(content, output_id=7, version=21)

    assert len(entries) == 3
    by_title = {e["title"]: e for e in entries}
    assert by_title["Customer Interview"]["level"] == "C"
    assert by_title["Customer Interview"]["node_label"] == "SP Networks Operations"
    assert by_title["Customer Interview"]["section_count"] == 8
    # two questions per section
    assert by_title["Customer Interview"]["question_count"] == 16
    assert all(e["output_id"] == 7 and e["version"] == 21 for e in entries)


def test_flatten_carries_the_title_so_the_caller_can_index_the_file():
    """The frontend fetches whole-file content, so it needs the key to index by."""
    content = {"Only Interview": _script("L1", "Fleet", 4)}
    assert flatten_script_file(content, output_id=1, version=1)[0]["title"] == "Only Interview"


def test_flatten_skips_placeholder_and_test_stubs():
    """Maya wrote {'test': true} and {'placeholder': ...} files while chunking."""
    assert flatten_script_file({"test": True}, 1, 1) == []
    assert flatten_script_file({"placeholder": "splitting into separate files"}, 1, 1) == []


def test_flatten_skips_non_dict_values():
    """A top-level key whose value is not an interview object is not an interview."""
    content = {"real": _script("C", "Node", 2), "notes": "some free text", "count": 3}
    entries = flatten_script_file(content, 1, 1)
    assert [e["title"] for e in entries] == ["real"]


def test_flatten_tolerates_missing_sections_and_level():
    entry = flatten_script_file({"Bare": {"node_label": "N"}}, 1, 1)[0]
    assert entry["section_count"] == 0
    assert entry["question_count"] == 0
    assert entry["level"] == ""
    assert entry["level_label"] == "Other"


def test_level_label_resolves_known_categories():
    entry = flatten_script_file({"X": _script("S", "Finance", 1)}, 1, 1)[0]
    assert entry["level_label"] == LEVEL_LABELS["S"] == "Corporate Services"


def test_dedupe_keeps_the_richest_entry_for_a_node():
    """Maya rewrote some interviews under new filenames rather than new versions."""
    thin = flatten_script_file({"PROPERTY VALUE CHAIN L1 Interview":
                                _script("L1", "Property Value Chain", 2)}, 1, 1)[0]
    rich = flatten_script_file({"Property Value Chain - L1 Strategic Interview":
                                _script("L1", "Property Value Chain", 6)}, 2, 2)[0]
    result = dedupe_and_order([thin, rich])

    assert len(result) == 1
    assert result[0]["section_count"] == 6, "kept the thinner interview"


def test_dedupe_normalises_case_and_punctuation_in_node_label():
    a = flatten_script_file({"A": _script("L2", "Asset Hierarchy & Classification", 3)}, 1, 1)[0]
    b = flatten_script_file({"B": _script("L2", "asset hierarchy and classification", 5)}, 2, 2)[0]
    # '&' vs 'and' is not normalised - only case, punctuation and spacing are
    assert len(dedupe_and_order([a, b])) == 2

    c = flatten_script_file({"C": _script("L2", "ASSET HIERARCHY & CLASSIFICATION!", 7)}, 3, 3)[0]
    merged = dedupe_and_order([a, c])
    assert len(merged) == 1
    assert merged[0]["section_count"] == 7


def test_dedupe_breaks_ties_on_version():
    a = flatten_script_file({"A": _script("C", "Same Node", 4)}, 1, 10)[0]
    b = flatten_script_file({"B": _script("C", "Same Node", 4)}, 2, 20)[0]
    assert dedupe_and_order([a, b])[0]["version"] == 20


def test_order_is_category_then_level_then_node():
    entries = []
    for level, node in [("L2", "Zeta"), ("C", "Beta"), ("L0", "Alpha"), ("A", "Gamma"),
                        ("F", "Delta"), ("S", "Epsilon"), ("L1", "Eta"), ("L3", "Theta")]:
        entries += flatten_script_file({f"{level}-{node}": _script(level, node, 1)}, 1, 1)
    assert [e["level"] for e in dedupe_and_order(entries)] == LEVEL_ORDER


def test_unknown_level_sorts_last():
    known = flatten_script_file({"K": _script("L3", "Known", 1)}, 1, 1)[0]
    odd = flatten_script_file({"O": _script("ZZ", "Odd", 1)}, 2, 2)[0]
    assert [e["level"] for e in dedupe_and_order([odd, known])] == ["L3", "ZZ"]


def test_dedupe_script_map_preserves_title_keys_and_drops_duplicates():
    """The endpoint returns title -> script, so dedupe must preserve that shape."""
    scripts = {
        "PROPERTY VALUE CHAIN L1 Interview": _script("L1", "Property Value Chain", 2),
        "Property Value Chain - L1 Interview": _script("L1", "Property Value Chain", 6),
        "Fleet Value Chain L1 Interview": _script("L1", "Fleet Value Chain", 4),
    }
    result = dedupe_script_map(scripts)
    assert set(result) == {"Property Value Chain - L1 Interview", "Fleet Value Chain L1 Interview"}
    assert result["Property Value Chain - L1 Interview"]["node_label"] == "Property Value Chain"


def test_dedupe_script_map_drops_non_interview_entries():
    assert dedupe_script_map({"notes": "free text", "n": 1}) == {}
    assert dedupe_script_map({"test": True}) == {}


def test_dedupe_script_map_tolerates_bad_input():
    assert dedupe_script_map(None) == {}
    assert dedupe_script_map([]) == {}


def test_flatten_keeps_real_interviews_alongside_stub_keys():
    """The endpoint merges every versioned file into one map, so stub keys from
    Maya's chunking files sit beside real interviews. Rejecting the whole map on
    seeing one stub key discarded all 30 interviews."""
    merged = {
        "test": True,
        "placeholder": "splitting into separate files",
        "Real Interview": _script("C", "Node A", 3),
    }
    entries = flatten_script_file(merged, 1, 1)
    assert [e["title"] for e in entries] == ["Real Interview"]
    assert set(dedupe_script_map(merged)) == {"Real Interview"}
