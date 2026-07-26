# api/services/interview_scripts_service.py
"""Build a readable index of Maya Patel's interview scripts.

Maya writes each batch of scripts to its own file, and a single file can hold
several interviews keyed by title. The raw agent_outputs list therefore shows
cryptic file-derived types such as `interview_scripts_l2_1`, which tells a
consultant nothing about what is inside.

This flattens those files into the unit that actually matters - one interview per
value chain stage - so the UI can group them by stakeholder category.
"""
import re

# Display order: stakeholder categories first, then the value chain levels.
LEVEL_ORDER = ["C", "A", "F", "S", "L0", "L1", "L2", "L3"]

LEVEL_LABELS = {
    "C": "Customer",
    "A": "Audit",
    "F": "Frontline",
    "S": "Corporate Services",
    "L0": "L0 - Portfolio",
    "L1": "L1 - Value Chain",
    "L2": "L2 - Stage",
    "L3": "L3 - Activity",
}

def _looks_like_interview(value: object) -> bool:
    """An interview is an object carrying at least a node label or sections."""
    return isinstance(value, dict) and ("node_label" in value or "sections" in value)


def _count_questions(sections: list) -> int:
    total = 0
    for section in sections or []:
        if isinstance(section, dict):
            total += len(section.get("questions") or [])
    return total


def flatten_script_file(content: dict, output_id: int, version: int) -> list[dict]:
    """Turn one script file into one entry per interview it contains.

    `title` is the file's top-level key, and must survive into the entry so callers
    can index the content by it.

    Stub entries are rejected per value, not per file: Maya's `{"test": true}` and
    `{"placeholder": ...}` files contribute keys to the merged map that the endpoint
    builds across every version, so rejecting a whole map because it contains one
    stub key would discard every real interview alongside it.
    """
    if not isinstance(content, dict):
        return []

    entries: list[dict] = []
    for title, script in content.items():
        if not _looks_like_interview(script):
            continue
        sections = script.get("sections") or []
        level = str(script.get("level") or "").strip()
        entries.append({
            "output_id": output_id,
            "version": version,
            "title": title,
            "level": level,
            "level_label": LEVEL_LABELS.get(level, "Other"),
            "node_label": str(script.get("node_label") or title),
            "section_count": len(sections) if isinstance(sections, list) else 0,
            "question_count": _count_questions(sections if isinstance(sections, list) else []),
        })
    return entries


def _dedupe_key(node_label: str) -> str:
    """Normalise a node label for comparison: case, punctuation and spacing only.

    Deliberately conservative. Merging '&' with 'and', or stripping words like
    'Strategic', would silently collapse interviews that are genuinely different.
    """
    lowered = node_label.casefold()
    # Drop a leading ordinal mark - Maya numbered some stages (①, ②) and the mark
    # is presentational ordering, not part of the stage's identity.
    lowered = re.sub(r"^[^a-z]+", "", lowered)
    stripped = re.sub(r"[^\w\s]", " ", lowered)
    return re.sub(r"\s+", " ", stripped).strip()


def _richness(entry: dict) -> tuple:
    return (entry["question_count"], entry["section_count"], entry["version"])


def dedupe_and_order(entries: list[dict]) -> list[dict]:
    """Keep the richest interview per node label, ordered by category then node.

    Maya rewrote some interviews under a new filename rather than as a new version
    of the same output, so two current outputs can describe the same stage. The
    richest - most questions, then most sections, then latest version - wins.
    """
    best: dict[str, dict] = {}
    for entry in entries:
        key = _dedupe_key(entry["node_label"])
        if key not in best or _richness(entry) > _richness(best[key]):
            best[key] = entry

    def sort_key(entry: dict) -> tuple:
        level = entry["level"]
        rank = LEVEL_ORDER.index(level) if level in LEVEL_ORDER else len(LEVEL_ORDER)
        return (rank, level, entry["node_label"].casefold())

    return sorted(best.values(), key=sort_key)


def dedupe_script_map(scripts: dict) -> dict:
    """Keep the richest interview per node label, preserving the title -> script shape.

    GET /{slug}/interview-scripts merges every versioned file keyed by interview
    title, so a stage Maya rewrote under a new title appears twice. Deduping here
    means the UI shows one card per value chain stage without any frontend change.
    Entries that are not interviews are dropped - they are not renderable anyway.
    """
    if not isinstance(scripts, dict):
        return {}
    kept = {e["title"] for e in dedupe_and_order(flatten_script_file(scripts, 0, 0))}
    return {title: body for title, body in scripts.items() if title in kept}
