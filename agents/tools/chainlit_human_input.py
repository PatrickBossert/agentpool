# agents/tools/chainlit_human_input.py
"""
ChainlitHumanInputTool — HumanInputTool variant for Chainlit sessions.

Uses cl.AskUserMessage to pause crew execution and surface HITL prompts
as native Chainlit input widgets. The sync _run() inherited from
HumanInputTool (SQLite polling) is not used in this path.
"""
import chainlit as cl
from agents.tools.human_input import HumanInputTool
from agents.tools._db import insert_hitl_review, complete_hitl_review

_DEFAULT_HITL_TIMEOUT = 86400  # 24 hours — matches HumanInputTool


class ChainlitHumanInputTool(HumanInputTool):
    name: str = "HumanInputTool"  # must match — task descriptions reference this name

    async def _arun(self, prompt: str) -> str:
        try:
            review_id = insert_hitl_review(
                slug=self.slug, run_id=self.run_id, prompt=prompt
            )
        except Exception as e:
            return f"Error: could not create review record — {e}"

        res = await cl.AskUserMessage(
            content=prompt, timeout=_DEFAULT_HITL_TIMEOUT
        ).send()
        response = res["output"] if res else "timeout: no response received"

        complete_hitl_review(slug=self.slug, review_id=review_id, decision=response)
        return response
