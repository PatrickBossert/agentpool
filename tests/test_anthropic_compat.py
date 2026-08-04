# tests/test_anthropic_compat.py
"""A conversation resumed after a review gate must still end with a user message.

CrewAI's Anthropic provider guarantees the *first* message is from a user
(`_format_messages_for_anthropic`, "Ensure first message is from user") and has no
equivalent guard for the last. When a run resumes after a human requests changes, the last
message is the agent's own, and the API refuses it:

    400 invalid_request_error - This model does not support assistant message prefill.
                                The conversation must end with a user message.

That killed run 15 of sp-gs-am at 00:48 on 4 August, nine minutes after the revision was
submitted, after every output had been written successfully. Until it is fixed the review
gate is approve-or-lose-the-run.

The fix belongs here rather than in the tool that raises the gate: agents/tools/human_input.py
is not ours to change, and the defect is in how the provider assembles messages, not in how
the answer is captured.
"""
import pytest

from agents.anthropic_compat import ensure_conversation_ends_with_user


@pytest.fixture(autouse=True)
def patched():
    ensure_conversation_ends_with_user()


def _format(messages):
    from crewai.llms.providers.anthropic.completion import AnthropicCompletion

    llm = AnthropicCompletion(model="claude-sonnet-4-6", api_key="not-used")
    return llm._format_messages_for_anthropic(messages)


def test_a_conversation_ending_with_the_agent_gains_a_user_turn():
    formatted, _ = _format([
        {"role": "user", "content": "Map the value chain"},
        {"role": "assistant", "content": "Here is the model"},
    ])
    assert formatted[-1]["role"] == "user"


def test_a_conversation_already_ending_with_a_user_is_untouched():
    # Every ordinary turn ends this way. Appending unconditionally would put a spurious
    # message into every single request the application makes.
    original = [
        {"role": "user", "content": "Map the value chain"},
        {"role": "assistant", "content": "Here is the model"},
        {"role": "user", "content": "Revise the fleet maintainer"},
    ]
    formatted, _ = _format(original)
    assert formatted[-1]["content"] == "Revise the fleet maintainer"
    assert len(formatted) == 3


def test_the_first_message_is_still_forced_to_be_a_user():
    # The upstream guard this sits beside must keep working - a patch that replaced it
    # rather than extending it would trade one rejection for another.
    formatted, _ = _format([{"role": "assistant", "content": "Unprompted"}])
    assert formatted[0]["role"] == "user"
    assert formatted[-1]["role"] == "user"


def test_applying_the_patch_twice_does_not_append_twice():
    """Nested wrappers would not double-append - the inner one leaves a user message last,
    so the outer finds nothing to do - but the output is what callers depend on, so it is
    pinned here rather than left to that reasoning holding after the next edit."""
    ensure_conversation_ends_with_user()
    ensure_conversation_ends_with_user()
    formatted, _ = _format([
        {"role": "user", "content": "Map it"},
        {"role": "assistant", "content": "Done"},
    ])
    assert [m["role"] for m in formatted] == ["user", "assistant", "user"]


def test_the_system_message_still_comes_back():
    formatted, system = _format([
        {"role": "system", "content": "You are Alex"},
        {"role": "user", "content": "Map it"},
        {"role": "assistant", "content": "Done"},
    ])
    assert system == "You are Alex"
    assert formatted[-1]["role"] == "user"
