# agents/anthropic_compat.py
"""Keep CrewAI's Anthropic provider from sending a conversation that ends with the agent.

CrewAI's `_format_messages_for_anthropic` guarantees the **first** message is from a user -
its own comment says "Ensure first message is from user (Anthropic requirement)" - and has
no equivalent guard for the last. In ordinary turns that does not matter: a conversation
ends with a tool result or a fresh instruction, both of which are user messages.

It matters when a run resumes after a human requests changes at a review gate. The last
message is then the agent's own output, and the API refuses the request:

    400 invalid_request_error - This model does not support assistant message prefill.
                                The conversation must end with a user message.

That killed run 15 of sp-gs-am, nine minutes after the revision was submitted and after
every output had already been written. Until it is fixed, the review gate is
approve-or-lose-the-run, which makes the revision loop unusable.

**Why a patch rather than a fix at the source.** The defect is in a vendored dependency, so
editing it in place would vanish on the next install. The alternative seam is
`agents/tools/human_input.py`, which is not ours to change - and the fault is in how the
provider assembles messages, not in how the answer is captured. Applied from `agents/llm.py`,
the single place this application constructs an LLM.

Remove this when CrewAI guards the last message as it already guards the first.
"""
from __future__ import annotations

_MARKER = "_agentpool_trailing_user_patch"

# Neutral, and only ever seen by the model. Anthropic requires a user turn to close the
# conversation; it does not require that turn to say anything in particular.
_CONTINUATION = "Continue."


def ensure_conversation_ends_with_user() -> None:
    """Make the Anthropic provider close every conversation with a user message.

    Idempotent by marker, and safe even without it: nested wrappers do not double-append,
    because the inner one leaves a user message last and the outer then sees nothing to do.
    The marker stops the nesting itself - every re-import would otherwise add a frame to
    every message-formatting call, for no gain.
    """
    from crewai.llms.providers.anthropic.completion import AnthropicCompletion

    if getattr(AnthropicCompletion, _MARKER, False):
        return

    original = AnthropicCompletion._format_messages_for_anthropic

    def _format_messages_for_anthropic(self, messages):  # type: ignore[no-untyped-def]
        formatted, system_message = original(self, messages)
        # Extends the upstream first-message guard rather than replacing it - trading one
        # rejection for another would be no improvement.
        if formatted and formatted[-1].get("role") == "assistant":
            formatted.append({"role": "user", "content": _CONTINUATION})
        return formatted, system_message

    AnthropicCompletion._format_messages_for_anthropic = _format_messages_for_anthropic
    setattr(AnthropicCompletion, _MARKER, True)
