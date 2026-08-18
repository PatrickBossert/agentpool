# tests/test_human_input.py
"""A review gate opens, waits on the database, and notifies nobody.

This file used to pin the payload `HumanInputTool` posted to n8n - specifically the
`review_url` in it, which had resolved to localhost on a path with a `/projects/` segment the
router does not define, so it 404d wherever a reviewer opened it. n8n is retired and there is
no payload to pin.

What replaces those tests is the fact itself, asserted rather than described: the tool makes no
outbound HTTP call, and the gate still opens and still closes on a database decision. An
absence is the easiest thing in a codebase to lose track of, and this slice removed a
notification without building one, so the absence is what gets the guard.
"""
from unittest.mock import patch

import pytest

# Imported at module scope, deliberately. Importing it inside a test that watches `httpx` would
# put the import under the watch, and importing `crewai.tools` pulls in LiteLLM, which fetches
# its model cost map over HTTP on first import. That call is nothing to do with this tool, and
# it happens exactly once per process - so a guard that included the import passed in the full
# suite, where something has already imported crewai, and failed when this file ran alone.
# CLAUDE.md's rule applies to a guard as much as to anything: when a test passes in the suite
# and fails alone, distrust whichever result depends on what ran before it.
from agents.tools.human_input import HumanInputTool


def _run_to_a_decision(tool, watchers=()):
    """Drive one full gate, exiting the poll on its first read, under any extra watchers.

    `time.sleep` and `get_review_decision` are patched so the loop does not block for real;
    `insert_hitl_review` is patched so nothing touches a database. Everything else - including
    any network call the tool might make - runs as it would in a crew, and the watchers see
    only what `_run` itself does.
    """
    from contextlib import ExitStack

    with ExitStack() as stack:
        stack.enter_context(
            patch("agents.tools.human_input.insert_hitl_review", return_value=1)
        )
        stack.enter_context(
            patch("agents.tools.human_input.get_review_decision", return_value=("approved", ""))
        )
        stack.enter_context(patch("agents.tools.human_input.time.sleep"))
        entered = [stack.enter_context(watcher) for watcher in watchers]
        return tool._run(prompt="Please review this output."), entered


def test_opening_a_review_gate_sends_nothing_anywhere():
    """The removal, asserted at the boundary rather than by reading the source.

    Patched on `httpx` itself, not on a name the module imports - the tool no longer imports
    `httpx` at all, so a patch aimed at `agents.tools.human_input.httpx` would raise
    `AttributeError` and a patch aimed at a name it might reacquire would have to guess which.
    This catches any client the module reaches for, however it gets hold of it, which a
    re-added `import httpx` inside `_run` was used to confirm.
    """
    import httpx

    tool = HumanInputTool(slug="acme-corp", run_id=7)
    result, (post, request, send) = _run_to_a_decision(
        tool,
        watchers=(
            patch.object(httpx, "post"),
            patch.object(httpx, "request"),
            patch.object(httpx.Client, "send"),
        ),
    )

    assert result == "approved", "the gate did not complete - this proves nothing about egress"
    post.assert_not_called()
    request.assert_not_called()
    send.assert_not_called()


def test_the_gate_still_opens_and_still_closes_on_a_database_decision():
    """The mechanism the notification was never part of.

    The webhook post was a nudge sent between the insert and the poll. Removing it cannot
    break a gate, and this is what says so: the review is recorded, the loop reads a decision,
    and the reviewer's notes come back to the agent.
    """
    tool = HumanInputTool(slug="acme-corp", run_id=7)
    with patch("agents.tools.human_input.insert_hitl_review", return_value=42) as inserted, \
         patch(
             "agents.tools.human_input.get_review_decision",
             return_value=("changes_requested", "tighten section 3"),
         ), \
         patch("agents.tools.human_input.time.sleep"):
        result = tool._run(prompt="Please review this output.")

    inserted.assert_called_once_with(slug="acme-corp", run_id=7, prompt="Please review this output.")
    assert result == "tighten section 3"


def test_a_rejection_still_terminates_the_run():
    """The other exit from the loop, which no notification was ever involved in."""
    tool = HumanInputTool(slug="acme-corp", run_id=7)
    with patch("agents.tools.human_input.insert_hitl_review", return_value=1), \
         patch(
             "agents.tools.human_input.get_review_decision",
             return_value=("rejected", "not what was asked for"),
         ), \
         patch("agents.tools.human_input.time.sleep"):
        with pytest.raises(RuntimeError, match="not what was asked for"):
            tool._run(prompt="Please review this output.")


def test_the_auto_respond_short_circuit_sends_nothing_either():
    """The path that never reached the webhook, kept so the guard covers both exits.

    `test_auto_respond` completes the review immediately and returns before the poll. It was
    already above the webhook post, so it is the one branch this slice did not change - and a
    guard on egress that only covered the changed branch would be the weaker half of the pair.
    """
    import httpx

    tool = HumanInputTool(slug="acme-corp", run_id=7, test_auto_respond="approved")
    result, (post, completed) = _run_to_a_decision(
        tool,
        watchers=(
            patch.object(httpx, "post"),
            patch("agents.tools.human_input.complete_hitl_review"),
        ),
    )

    assert result == "approved"
    completed.assert_called_once()
    post.assert_not_called()
