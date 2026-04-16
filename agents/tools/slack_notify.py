# agents/tools/slack_notify.py
"""SlackNotifyTool — fire-and-forget Slack notification via n8n webhook."""
import httpx
from pathlib import Path
from crewai.tools import BaseTool
from api.config import get_settings, load_project_config


class SlackNotifyTool(BaseTool):
    name: str = "SlackNotifyTool"
    description: str = "Send a notification message to the project's Slack channel via n8n."
    slug: str

    def _run(self, message: str) -> str:
        settings = get_settings()
        if not settings.n8n_webhook_url:
            return "notification skipped (no webhook configured)"
        try:
            config = load_project_config(Path(settings.projects_dir) / self.slug)
            slack_channel = config.get("slack_channel", "")
            httpx.post(
                settings.n8n_webhook_url,
                json={
                    "event_type": "crew_notification",
                    "project_slug": self.slug,
                    "slack_channel": slack_channel,
                    "message": message,
                },
                timeout=5.0,
            )
            return "notification sent"
        except Exception as e:
            return f"notification failed (non-fatal): {e}"
