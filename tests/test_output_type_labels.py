# tests/test_output_type_labels.py
"""An output type is called one thing, and every type an agent owns has a name.

`OUTPUT_TYPE_LABELS` was declared three times - in `RerunDialog.tsx`, `AgentStatusTab.tsx` and
`Documents.tsx` - and the three had already diverged, not in wording but in scope. Only the
rerun dialog knew `architecture_register`; only the other two knew `roadmap_data`,
`initiative_register`, `docx` and `value_chain_model`. Each map has a title-casing fallback, so
a missing entry is silent: the same artefact read "As-Is Capabilities" in one dialog and
"Architecture Register" in another, and `docx` read "Docx".

Detected by shape rather than by name. A test looking for the identifier passes the moment
someone renames the fourth copy, which is the failure mode a grep guard has.
"""
from __future__ import annotations

import re
from pathlib import Path

from agents.tools.ownership import OUTPUT_OWNERS

UI_SRC = Path(__file__).resolve().parent.parent / "ui" / "src"

# Types distinctive enough that a map containing several of them is an output-type label map
# whatever it has been called. Chosen from the entries the three copies shared.
MARKERS = frozenset({
    "interview_scripts",
    "portfolio_register",
    "stakeholder_engagement_plan",
    "interview_transcripts",
    "activity_insights",
})


def _label_maps() -> dict[Path, dict[str, str]]:
    """Every `Record<string, string>` literal under ui/src that labels output types."""
    found: dict[Path, dict[str, str]] = {}
    for path in sorted(UI_SRC.rglob("*.ts*")):
        if "__tests__" in path.parts:
            continue
        for block in re.findall(r"Record<string, string> = \{(.*?)\n\}", path.read_text(), re.S):
            entries = dict(re.findall(r"(\w+):\s*'([^']*)'", block))
            if len(MARKERS & set(entries)) >= 3:
                found[path] = {**found.get(path, {}), **entries}
    return found


def test_the_detector_finds_the_one_map_that_exists():
    """Guard the guard: a detector that matched nothing would make both tests below pass."""
    maps = _label_maps()
    assert maps, "no output-type label map found at all - the detector has drifted"
    assert MARKERS <= set(next(iter(maps.values())))


def test_only_one_module_labels_output_types():
    maps = _label_maps()
    assert len(maps) == 1, (
        f"{len(maps)} modules declare output-type labels: "
        f"{sorted(str(p.relative_to(UI_SRC)) for p in maps)}. Import `outputLabel` from "
        f"components/outputTypeLabels instead - each of these has a title-casing fallback, so "
        f"a copy that is merely missing an entry disagrees with the others in silence."
    )


def test_every_output_type_an_agent_owns_has_a_label():
    """The fallback makes a gap invisible, so the roll is asserted rather than trusted.
    `OUTPUT_OWNERS` is the roll: one owner per output type, enforced by `check_write`."""
    labels = next(iter(_label_maps().values()))
    unlabelled = sorted(set(OUTPUT_OWNERS) - set(labels))
    assert not unlabelled, (
        f"{unlabelled} are written by an agent and have no label, so they render as a "
        f"title-cased key wherever an output is listed"
    )
