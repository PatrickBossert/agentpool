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
    )


def get_pam_llm() -> LLM:
    """PAM always uses claude-opus-4-6, never routes to sensitive/local."""
    settings = get_settings()
    return LLM(
        model=PAM_MODEL,
        api_key=settings.anthropic_api_key,
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
