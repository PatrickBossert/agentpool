"""Compares two report snapshots so Pamela can say what changed.

Risks and issues are derived fresh on every report and have no stable id, so
`title` is the identity - it is the field the derivation uses to describe a risk.
"""


def _titles(report: dict | None, key: str) -> list[str]:
    if not report:
        return []
    return [r.get("title", "") for r in (report.get(key) or []) if r.get("title")]


def _milestone_rag(report: dict | None) -> dict:
    """Key milestones on milestone_key - the stable identity. title is
    user-editable, so keying on it would read a rename as one milestone
    disappearing and another appearing."""
    if not report:
        return {}
    out = {}
    for m in report.get("milestones") or []:
        key = m.get("milestone_key")
        if key:
            out[key] = {"title": m.get("title"), "rag": m.get("rag")}
    return out


def diff_reports(previous: dict | None, current: dict) -> dict:
    """Describe what changed between two reports.

    A first report has nothing to compare against and reports no changes, rather
    than announcing every existing risk as new.
    """
    is_first = previous is None

    prev_risks, curr_risks = set(_titles(previous, "risks")), set(_titles(current, "risks"))
    prev_issues, curr_issues = set(_titles(previous, "issues")), set(_titles(current, "issues"))

    new_risks = [] if is_first else sorted(curr_risks - prev_risks)
    resolved_risks = [] if is_first else sorted(prev_risks - curr_risks)
    new_issues = [] if is_first else sorted(curr_issues - prev_issues)
    resolved_issues = [] if is_first else sorted(prev_issues - curr_issues)

    milestone_changes = []
    if not is_first:
        prev_rag, curr_rag = _milestone_rag(previous), _milestone_rag(current)
        for key, curr_entry in curr_rag.items():
            prev_entry = prev_rag.get(key)
            if prev_entry and prev_entry["rag"] != curr_entry["rag"]:
                milestone_changes.append({
                    "name": curr_entry["title"],
                    "from": prev_entry["rag"],
                    "to": curr_entry["rag"],
                })

    def _plural(n: int, word: str) -> str:
        return f"{n} {word}{'' if n == 1 else 's'}"

    if is_first:
        summary = "First report for this project - no previous position to compare against."
    else:
        parts = []
        if new_risks:
            parts.append(_plural(len(new_risks), "new risk"))
        if new_issues:
            parts.append(_plural(len(new_issues), "new issue"))
        if resolved_risks:
            parts.append(_plural(len(resolved_risks), "risk") + " resolved")
        if resolved_issues:
            parts.append(_plural(len(resolved_issues), "issue") + " resolved")
        if milestone_changes:
            parts.append(_plural(len(milestone_changes), "milestone") + " changed status")
        summary = ", ".join(parts) if parts else "No change since the previous report."

    return {
        "is_first_report": is_first,
        "new_risks": new_risks,
        "resolved_risks": resolved_risks,
        "new_issues": new_issues,
        "resolved_issues": resolved_issues,
        "milestone_changes": milestone_changes,
        "summary": summary,
    }
