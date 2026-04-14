# agents/llm.py
from crewai import LLM
from api.config import get_settings


def get_crew_llm(llm_mode: str) -> LLM:
    """Return the LLM for crew agents based on the project's llm_mode setting."""
    settings = get_settings()
    if llm_mode == "sensitive":
        return LLM(
            model="openai/local-model",
            base_url=settings.llamacpp_base_url,
            api_key="not-needed",
        )
    # standard or fallback: use Anthropic directly
    return LLM(
        model="anthropic/claude-sonnet-4-6",
        api_key=settings.anthropic_api_key,
    )


def get_pam_llm() -> LLM:
    """PAM always uses claude-opus-4-6, never routes to sensitive/local."""
    settings = get_settings()
    return LLM(
        model="anthropic/claude-opus-4-6",
        api_key=settings.anthropic_api_key,
    )


def get_test_llm() -> LLM:
    """Cheap model for integration tests."""
    settings = get_settings()
    return LLM(
        model="anthropic/claude-haiku-4-5-20251001",
        api_key=settings.anthropic_api_key,
    )
