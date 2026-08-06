# api/services/tree_validation.py
"""Structural checks on value_chain_tree, run when the tree is written.

Pure by design: tree and previous registry in, warnings out. No file reads, no database, no
settings. That is what lets the tool path, the API and the tests all exercise the same
function, and what makes the fixtures in tests/test_tree_validator.py sufficient evidence.

Every check warns. None refuses. A refusal would block the run and lose the work; a silent
pass would lose the signal. Recording makes the gap a finding - the same move the ownership
work made with blocked_writes, where a refused write became the only surviving evidence
that the L0 was missing.
"""
from __future__ import annotations

ROLE_SUFFIXES = ("A", "S", "C", "F")


def _walk(nodes: list, parent_id: str | None = None):
    """Yield (node, parent_id) depth-first. Tolerates a missing or non-list children key."""
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        yield node, parent_id
        yield from _walk(node.get("children") or [], str(node.get("id", "")))


def _is_role_id(node_id: str) -> bool:
    return str(node_id).rsplit(".", 1)[-1] in ROLE_SUFFIXES


def validate_tree_structure(tree: list, previous_registry: dict | None) -> list[dict]:
    """Warnings about the new tree, judged against the previous registry.

    previous_registry is None on a first run. Only missing_l0 applies then - the root is
    required unconditionally, while the other two checks have no baseline to compare with
    and are skipped rather than guessed at.
    """
    warnings: list[dict] = []
    if not isinstance(tree, list):
        return [{
            "subject": None, "code": "missing_l0", "measure": None,
            "detail": f"the tree is a {type(tree).__name__}, not a list of root nodes",
        }]

    # ── missing_l0 ────────────────────────────────────────────────────────────────
    roots = [n for n in tree if isinstance(n, dict)]
    root = next((n for n in roots if str(n.get("id")) == "0"), None)
    if root is None:
        top_l1 = [str(n.get("id")) for n in roots if n.get("level") == "L1"]
        warnings.append({
            "subject": None, "code": "missing_l0", "measure": None,
            "detail": (
                "the tree has no root node with id '0'. The registry is derived from the "
                "tree, so nothing can anchor at organisation level - no board interview, no "
                "governance theme. Top-level nodes found: "
                + (", ".join(top_l1) if top_l1 else "none")
            ),
        })
    elif root.get("level") != "L0":
        warnings.append({
            "subject": "0", "code": "missing_l0", "measure": None,
            "detail": f"the root node '0' has level {root.get('level')!r}, expected 'L0'",
        })
    else:
        detached = [
            str(n.get("id")) for n in roots
            if str(n.get("id")) != "0" and n.get("level") == "L1"
        ]
        if detached:
            warnings.append({
                "subject": None, "code": "missing_l0", "measure": None,
                "detail": (
                    "these L1 entities sit beside the root rather than under it, so they do "
                    "not descend from the L0: " + ", ".join(sorted(detached))
                ),
            })

    if previous_registry is None:
        return warnings

    prev = {
        str(a["id"]): a
        for a in (previous_registry.get("activities") or [])
        if isinstance(a, dict) and a.get("id") is not None
    }
    new_nodes = {str(n.get("id")): n for n, _ in _walk(tree) if n.get("id") is not None}

    # ── missing_role_node ─────────────────────────────────────────────────────────
    for node_id, entry in sorted(prev.items()):
        if not entry.get("active", True):
            continue
        if _is_role_id(node_id) and node_id not in new_nodes:
            warnings.append({
                "subject": node_id, "code": "missing_role_node", "measure": None,
                "detail": (
                    f"role node {node_id} ({entry.get('label', '')!r}) was in the previous "
                    f"registry and is absent from this tree. Role nodes are what give the "
                    f"outside-in and bottom-up view; dropping one silently removes a "
                    f"stakeholder category from assignment and from synthesis."
                ),
            })

    # ── id_redefined ──────────────────────────────────────────────────────────────
    for node_id, node in sorted(new_nodes.items()):
        entry = prev.get(node_id)
        if entry is None or not entry.get("active", True):
            continue
        old_label = str(entry.get("label", "")).strip()
        new_label = str(node.get("label", "")).strip()
        if old_label and new_label and old_label != new_label:
            warnings.append({
                "subject": node_id, "code": "id_redefined", "measure": None,
                "detail": (
                    f"id {node_id} meant {old_label!r} and now means {new_label!r}. The "
                    f"ledger may grow and may retire, but may not redefine - Architecture's "
                    f"capability model is built against these ids."
                ),
            })
    return warnings
