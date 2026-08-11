# api/services/coverage_validation.py
"""Which value chain nodes have no interview script.

The contract is one interview per node. Stakeholders are assigned to scripts separately, so one
script may serve several people - five frontline roles against one frontline instrument - and the
count of interviews conducted is not the count of scripts owed.

Matches on node_id rather than level, deliberately. The registry files a role node at its
structural tier (0.A is L0) and the script files it by perspective (0.A is A), so a level
comparison would report all six role nodes uncovered while they are covered. Node ids are
unambiguous in both artefacts.
"""

_MAX_NAMED = 12


def validate_node_coverage(scripts: dict, registry: dict) -> list[dict]:
    """Zero warnings when every active activity has a script, otherwise exactly one.

    One warning rather than one per node: seventy-three findings would bury the surface they are
    reported into, and the actionable fact is the set, not each member of it.
    """
    owed = [a.get("id") for a in registry.get("activities", []) if a.get("active", True)]
    if not owed:
        return []
    covered = {s.get("node_id") for s in scripts.values() if isinstance(s, dict)}
    missing = [node_id for node_id in owed if node_id not in covered]
    if not missing:
        return []

    named = ", ".join(missing[:_MAX_NAMED])
    if len(missing) > _MAX_NAMED:
        named += f", and {len(missing) - _MAX_NAMED} more"
    return [{
        "subject": None,
        "code": "incomplete_coverage",
        "measure": round((len(owed) - len(missing)) / len(owed), 4),
        "detail": (
            f"{len(owed) - len(missing)} of {len(owed)} value chain nodes have an interview "
            f"script. Missing: {named}. Every active node needs one - re-run to add the "
            f"remainder; existing scripts are kept."
        ),
    }]
