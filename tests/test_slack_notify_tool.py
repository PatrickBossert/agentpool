# tests/test_slack_notify_tool.py
"""Unit tests for SlackNotifyTool."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


@pytest.fixture(autouse=True)
def clear_settings():
    import api.config as cfg
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _make_tool(slug="acme"):
    from agents.tools.slack_notify import SlackNotifyTool
    return SlackNotifyTool(slug=slug)


def test_run_posts_to_webhook(tmp_path, monkeypatch):
    """_run posts a JSON body with event_type='crew_notification' to the n8n webhook."""
    import yaml
    project_dir = tmp_path / "acme"
    project_dir.mkdir()
    (project_dir / "config.yaml").write_text(yaml.dump({"slack_channel": "#eng"}))

    import api.config as cfg
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("N8N_WEBHOOK_URL", "http://n8n.local/webhook/agentpool")
    cfg.get_settings.cache_clear()

    mock_resp = MagicMock()
    with patch("agents.tools.slack_notify.httpx.post", return_value=mock_resp) as mock_post:
        tool = _make_tool()
        result = tool._run("hello world")

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    payload = kwargs["json"]
    assert payload["event_type"] == "crew_notification"
    assert payload["project_slug"] == "acme"
    assert payload["slack_channel"] == "#eng"
    assert payload["message"] == "hello world"
    assert result == "notification sent"


def test_run_skipped_when_no_webhook(tmp_path, monkeypatch):
    """When N8N_WEBHOOK_URL is not set, _run returns a skip message without raising."""
    import api.config as cfg
    # Override with empty string — delenv alone falls back to .env file if present
    monkeypatch.setenv("N8N_WEBHOOK_URL", "")
    cfg.get_settings.cache_clear()

    with patch("agents.tools.slack_notify.httpx.post") as mock_post:
        tool = _make_tool()
        result = tool._run("msg")

    mock_post.assert_not_called()
    assert "skipped" in result


def test_run_skipped_on_http_error(tmp_path, monkeypatch):
    """If httpx.post raises, _run returns a failure string rather than propagating."""
    import yaml, httpx
    project_dir = tmp_path / "acme"
    project_dir.mkdir()
    (project_dir / "config.yaml").write_text(yaml.dump({"slack_channel": ""}))

    import api.config as cfg
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("N8N_WEBHOOK_URL", "http://n8n.local/webhook/agentpool")
    cfg.get_settings.cache_clear()

    with patch("agents.tools.slack_notify.httpx.post", side_effect=httpx.ConnectError("timeout")):
        tool = _make_tool()
        result = tool._run("msg")

    assert "non-fatal" in result or "failed" in result


def test_run_includes_slug_in_payload(tmp_path, monkeypatch):
    """The project_slug field in the payload matches the tool's slug."""
    import yaml
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()
    (project_dir / "config.yaml").write_text(yaml.dump({"slack_channel": ""}))

    import api.config as cfg
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("N8N_WEBHOOK_URL", "http://n8n.local/webhook/agentpool")
    cfg.get_settings.cache_clear()

    captured = {}
    def fake_post(url, *, json, timeout):
        captured.update(json)
        return MagicMock()

    with patch("agents.tools.slack_notify.httpx.post", side_effect=fake_post):
        tool = _make_tool(slug="myproject")
        tool._run("test")

    assert captured["project_slug"] == "myproject"
