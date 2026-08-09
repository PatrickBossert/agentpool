# agents/llm.py
"""get_test_llm only. Every production LLM is now built by agents/model_registry.py -
get_crew_llm, get_pam_llm, and get_haiku_llm were retired in the per-agent model selection
refactor once no crew factory had a caller left for them.
"""
from crewai import LLM
from api.config import get_settings
from agents.anthropic_compat import ensure_conversation_ends_with_user

# Applied here too, in case a test imports agents.llm without first importing
# agents.model_registry - idempotent by marker, so calling it from both costs nothing.
# See agents/anthropic_compat.py.
ensure_conversation_ends_with_user()


def get_test_llm() -> LLM:
    """Cheap model for integration tests - the only consumer of this module now.

    Crew factories accept an `llm: LLM | None` override for exactly this: integration tests
    inject this in place of whatever agents/model_registry.py would otherwise resolve.
    """
    settings = get_settings()
    return LLM(
        model="anthropic/claude-haiku-4-5-20251001",
        api_key=settings.anthropic_api_key,
    )
