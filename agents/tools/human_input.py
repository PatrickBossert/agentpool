# agents/tools/human_input.py
"""Pause a crew at a review gate and wait for a human decision.

**Nothing notifies the reviewer that a gate is open.** This tool used to post the review to an
n8n webhook - `review_id`, the prompt, the slug, the run id, and a dashboard link - which n8n
relayed to Slack. n8n is retired, the post is gone, and no channel replaced it. Say so here
rather than let a reader infer it from an absence: a reviewer learns a gate is waiting by
opening the dashboard, and until something pushes, an agent can sit on a gate for the full
24 hours below with nobody aware.

The gate itself is unaffected, and this is the distinction that made removing the post safe.
The post was a nudge; the mechanism is `insert_hitl_review` followed by the polling loop, which
ends when `PATCH /projects/{slug}/reviews/{id}` records a decision. That was true while the
webhook existed too - `settings.n8n_webhook_url` was optional and the post sat inside
`except Exception: pass`, so every deployment without n8n configured already ran exactly as
this does.

The intended replacement is a message push carrying a link and a token that brings the reviewer
to the content on the server, never the content itself - the shape the invite and reset loops
already run on. `deliver_reset` in `api/services/invite_service.py` is where that kind of
decision lives, and `FROM_EMAIL` naming an unverified Resend domain is why an administrator
handing over a link is the honest channel today. None of that is built. This tool has no
outbound call at all, and `tests/test_human_input.py` asserts that rather than describing it.
"""
import os
import time
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
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

        # Nothing is notified. See the module docstring: the review is now in the database and
        # visible on the dashboard, and a reviewer finds it by looking.

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
            if decision == "rejected":
                raise RuntimeError(
                    f"Output rejected by reviewer{': ' + notes if notes else ''}. "
                    "Crew run terminated."
                )
            if decision != "pending":
                return notes if notes else decision
