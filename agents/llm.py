# agents/llm.py
from crewai import LLM
from api.config import get_settings
from agents.pam import PAM_MODEL
from agents.anthropic_compat import ensure_conversation_ends_with_user

# Applied here because this is the only place the application builds an LLM. Without it, a
# run resumed after a human requests changes sends a conversation ending with the agent's
# own message and the API refuses it - which is what killed run 15 after every output had
# already been written. See agents/anthropic_compat.py.
ensure_conversation_ends_with_user()

# CrewAI routes "anthropic/*" models to its own AnthropicCompletion provider, which calls the
# Anthropic SDK directly - LiteLLM is not involved. That provider defaults to stream=False and
# passes timeout=None straight through, so the SDK client is built with no timeout whatsoever.
# A long non-streaming generation therefore holds an idle socket open with nothing flowing until
# the entire response lands, and a dropped connection surfaces as a bare
# "anthropic.APIConnectionError: Connection error." with no way to bound it. That is what killed
# discovery_mapping runs 22 and 23. Streaming keeps bytes moving so the connection is never idle,
# and the explicit timeout applies per read rather than to the whole call - it bounds a wedged
# socket without capping how long a legitimate generation may take.
_LONG_CALL_TRANSPORT = {"stream": True, "timeout": 600.0}


def get_crew_llm(llm_mode: str) -> LLM:
    """Return the LLM for crew agents based on the project's llm_mode setting."""
    settings = get_settings()
    if llm_mode == "sensitive":
        return LLM(
            model=f"openai/{settings.local_llm_model}",
            base_url=settings.llamacpp_base_url,
            api_key="not-needed",
        )
    # standard or fallback: use Anthropic directly
    # max_tokens=16384: the default 4096 clips large tool-call JSON outputs
    # (e.g. questionnaire scripts ~8K tokens, value chain tree ~2.5K tokens)
    return LLM(
        model="anthropic/claude-sonnet-4-6",
        api_key=settings.anthropic_api_key,
        max_tokens=16384,
        **_LONG_CALL_TRANSPORT,
    )


def get_pam_llm() -> LLM:
    """PAM always uses claude-opus-4-6, never routes to sensitive/local."""
    settings = get_settings()
    return LLM(
        model=PAM_MODEL,
        api_key=settings.anthropic_api_key,
        **_LONG_CALL_TRANSPORT,
    )


def get_test_llm() -> LLM:
    """Cheap model for integration tests."""
    settings = get_settings()
    return LLM(
        model="anthropic/claude-haiku-4-5-20251001",
        api_key=settings.anthropic_api_key,
    )


def get_haiku_llm() -> LLM:
    """For agents spec'd to use claude-haiku-4-5 in production (e.g. Portfolio Manager)."""
    settings = get_settings()
    return LLM(
        model="anthropic/claude-haiku-4-5-20251001",
        api_key=settings.anthropic_api_key,
    )
