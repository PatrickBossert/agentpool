# tests/test_human_input.py
"""Unit tests for HumanInputTool's webhook payload to n8n.

Task 10 fixed interview_url() to build links from public_url rather than the unset
frontend_url, and to route under /dashboard rather than a /projects/ segment the router
does not define. human_input.py had the same two defects in the review_url it posts to
n8n for HITL notifications - these tests pin the payload the webhook actually carries.
"""
from unittest.mock import MagicMock, patch

from api.config import get_settings


def _run_tool_and_capture_webhook_call(monkeypatch):
    """Drive HumanInputTool through a real HITL cycle with the webhook post mocked.

    Mocks at agents.tools.human_input.httpx.post - the real boundary where the webhook
    is sent - rather than assuming a helper builds the URL. Also mocks time.sleep and
    get_review_decision so the poll loop exits on its first iteration instead of
    blocking for real.
    """
    monkeypatch.setenv("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/agentpool")
    get_settings.cache_clear()

    from agents.tools.human_input import HumanInputTool

    tool = HumanInputTool(slug="acme-corp", run_id=7)

    with patch("agents.tools.human_input.insert_hitl_review", return_value=1), \
         patch("agents.tools.human_input.get_review_decision", return_value=("approved", "")), \
         patch("agents.tools.human_input.time.sleep"), \
         patch("agents.tools.human_input.httpx.post") as mock_post:
        result = tool._run(prompt="Please review this output.")

    get_settings.cache_clear()
    assert result == "approved"
    mock_post.assert_called_once()
    return mock_post.call_args.kwargs["json"]


def test_the_review_link_points_at_a_route_that_exists(monkeypatch):
    """The link goes to n8n and a human clicks it. It resolved to localhost, on a path with a
    /projects/ segment the router does not define, so it 404d wherever it was opened."""
    monkeypatch.setenv("PUBLIC_URL", "https://example.test")
    payload = _run_tool_and_capture_webhook_call(monkeypatch)
    url = payload["review_url"]
    assert url.startswith("https://example.test/dashboard/")
    assert "/projects/" not in url
    assert url.endswith("/reviews")


def test_the_review_link_strips_a_trailing_slash_from_public_url(monkeypatch):
    """A trailing slash in PUBLIC_URL is a plausible .env typo - it must not double up."""
    monkeypatch.setenv("PUBLIC_URL", "https://example.test/")
    payload = _run_tool_and_capture_webhook_call(monkeypatch)
    assert payload["review_url"] == "https://example.test/dashboard/acme-corp/reviews"
