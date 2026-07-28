"""'Flag any new risks' needs memory. This compares today's derived report with
the last stored one, keyed on the title field that identifies a risk."""
from api.services.report_diff_service import diff_reports


def _report(risks=(), issues=(), milestones=()):
    return {
        "risks": [{"severity": "high", "title": t} for t in risks],
        "issues": [{"severity": "medium", "title": t} for t in issues],
        "milestones": list(milestones),
    }


def test_first_report_reports_no_changes():
    """Otherwise every existing risk would be announced as new on day one."""
    d = diff_reports(None, _report(risks=["A", "B"]))
    assert d["is_first_report"] is True
    assert d["new_risks"] == []
    assert d["resolved_risks"] == []


def test_a_risk_in_both_reports_is_not_new():
    d = diff_reports(_report(risks=["A"]), _report(risks=["A"]))
    assert d["new_risks"] == []
    assert d["resolved_risks"] == []


def test_a_risk_only_in_the_current_report_is_new():
    d = diff_reports(_report(risks=["A"]), _report(risks=["A", "B"]))
    assert d["new_risks"] == ["B"]


def test_a_risk_that_has_gone_is_resolved():
    d = diff_reports(_report(risks=["A", "B"]), _report(risks=["A"]))
    assert d["resolved_risks"] == ["B"]


def test_issues_are_tracked_separately_from_risks():
    d = diff_reports(_report(issues=["X"]), _report(issues=["X", "Y"]))
    assert d["new_issues"] == ["Y"]
    assert d["new_risks"] == []


def test_milestone_rag_changes_are_reported():
    prev = {"risks": [], "issues": [],
            "milestones": [{"id": 1, "name": "Discovery", "rag": "green"}]}
    curr = {"risks": [], "issues": [],
            "milestones": [{"id": 1, "name": "Discovery", "rag": "amber"}]}
    d = diff_reports(prev, curr)
    assert d["milestone_changes"] == [
        {"name": "Discovery", "from": "green", "to": "amber"}
    ]


def test_summary_reads_as_prose():
    d = diff_reports(_report(risks=["A"]), _report(risks=["A", "B"], issues=["X"]))
    assert "1 new risk" in d["summary"]
    assert "1 new issue" in d["summary"]


def test_summary_says_nothing_changed_when_nothing_did():
    d = diff_reports(_report(risks=["A"]), _report(risks=["A"]))
    assert "No change" in d["summary"]


def test_missing_keys_are_tolerated():
    """A snapshot written by an older version may not have every key."""
    d = diff_reports({}, {})
    assert d["new_risks"] == []
    assert d["summary"]
