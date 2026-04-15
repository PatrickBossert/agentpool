# agents/tools/human_input.py
import os
import time
import httpx
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from api.config import get_settings
from agents.tools._db import insert_hitl_review, get_review_decision, complete_hitl_review

_DEFAULT_HITL_TIMEOUT = 86400  # 24 hours


class HumanInputToolInput(BaseModel):
    prompt: str = Field(
        description="The question or instruction to present to the human reviewer."
    )


class HumanInputTool(BaseTool):
    name: str = "HumanInputTool"
    description: str = (
        "Pause the crew and request a human response. "
        "Use for review approval checkpoints and stakeholder interview questions. "
        "Returns the human's response as a string. "
        "If the response contains revision notes, revise your output and call this tool again "
        "(maximum 3 times per output)."
    )
    args_schema: type[BaseModel] = HumanInputToolInput
    slug: str
    run_id: int
    test_auto_respond: str | None = None

    def _run(self, prompt: str) -> str:
        # Check for auto-respond (env var for tests, or instance attribute)
        auto = self.test_auto_respond or os.getenv("HITL_AUTO_RESPOND")

        try:
            review_id = insert_hitl_review(
                slug=self.slug, run_id=self.run_id, prompt=prompt
            )
        except Exception as e:
            return f"Error: could not create review record — {e}"

        if auto:
            complete_hitl_review(slug=self.slug, review_id=review_id, decision=auto)
            return auto

        # Notify n8n (fire and forget — don't fail the crew if n8n is unavailable)
        settings = get_settings()
        if settings.n8n_webhook_url:
            try:
                httpx.post(
                    settings.n8n_webhook_url,
                    json={
                        "review_id": review_id,
                        "prompt": prompt,
                        "project_slug": self.slug,
                        "run_id": self.run_id,
                        "review_url": (
                            f"{settings.frontend_url}/projects/{self.slug}/reviews"
                        ),
                    },
                    timeout=5.0,
                )
            except Exception:
                pass  # Don't block the crew if n8n is unreachable

        # Poll until the human updates the review via PATCH /projects/{slug}/reviews/{id}
        timeout_seconds = int(os.getenv("HITL_TIMEOUT_SECONDS", str(_DEFAULT_HITL_TIMEOUT)))
        deadline = time.monotonic() + timeout_seconds
        consecutive_errors = 0
        while True:
            time.sleep(5)
            if time.monotonic() > deadline:
                return "timeout: no human response received within the allowed window"
            try:
                decision, notes = get_review_decision(slug=self.slug, review_id=review_id)
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    return f"Error: could not read review decision after 5 attempts — {e}"
                continue
            if decision != "pending":
                return notes if notes else decision
