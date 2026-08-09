# agents/model_registry.py
"""Which model each agent runs on.

Agents declare a capability tier; the project's llm_mode binds that tier to a concrete model.
This mirrors agents/tools/registry.py, which maps an agent to its tools, and exists for the same
reason: knowledge that lives in eleven crew factories drifts. discovery_interviews_crew declared
llm_mode as a parameter and never read it, putting the Synthesis Analyst on a hosted model while
it held ChromaQueryTool over the project's own interview answers. Sixteen task-scoped reviews
passed it.

The mode is read here from the project's own row rather than accepted from the caller. A caller
that can pass the wrong mode is a caller that can leak.
"""
import json
import logging

from crewai import LLM

from api.config import get_settings
from api.models import ProjectSettings
from api.services.chroma_client import project_llm_mode
from agents.anthropic_compat import ensure_conversation_ends_with_user

ensure_conversation_ends_with_user()

_log = logging.getLogger(__name__)

# See agents/llm.py for why streaming and an explicit timeout are required: CrewAI's Anthropic
# provider defaults to stream=False with timeout=None, which killed discovery_mapping runs 22
# and 23. Streaming keeps bytes moving so the connection is never idle, and the explicit timeout
# applies per read rather than to the whole call - it bounds a wedged socket without capping how
# long a legitimate generation may take.
_LONG_CALL_TRANSPORT = {"stream": True, "timeout": 600.0}

# max_tokens=16384: the 4096 default clips large tool-call JSON outputs - questionnaire scripts
# run to ~8K tokens and the value chain tree to ~2.5K. Applied to both paths, because the local
# branch in the old get_crew_llm previously set nothing and clipped exactly those outputs.
_MAX_TOKENS = 16384


class LocalModelUnavailable(RuntimeError):
    """A sensitive project has no model configured for a tier.

    Raised rather than falling back. A hosted fallback would send client content to a third
    party, and borrowing the other tier's model would silently change what ran.
    """


# Fast is coordination and mechanical assembly. Deep is reasoning across a corpus, or producing a
# structure others inherit and cannot easily correct.
AGENT_TIER: dict[str, str] = {
    "interview_coordinator":       "fast",   # Taylor - builds the plan, creates sessions
    "stakeholder_interviewer":     "fast",   # Avery - creates sessions, waits, collects
    "stakeholder_manager":         "fast",   # Jordan - drafts outreach
    "portfolio_manager":           "fast",   # already deliberately on Haiku today
    "roadmap_generator":           "fast",   # sequences an existing register
    "visual_illustrator":          "deep",   # writes briefs grounded in real project data
    "interaction_designer":        "deep",   # Maya - the instruments the campaign runs on
    "synthesis_analyst":           "deep",   # Casey - reasons across every answer in a campaign
    "value_chain_mapper":          "deep",   # Alex - the spine everything downstream inherits
    "value_lever_analyst":         "deep",   # Morgan
    "value_proposition_generator": "deep",
    "enterprise_architect":        "deep",
    "initiative_identifier":       "deep",
    "requirements_capture":        "deep",
    "requirements_analyst":        "deep",
    "business_plan_generator":     "deep",
    "pam":                         "deep",   # no exemption - PAM can read project outputs
}

_TIER_SETTINGS = {
    ("fast", "standard"):  ("anthropic_fast_model", None),
    ("deep", "standard"):  ("anthropic_deep_model", None),
    ("fast", "sensitive"): ("local_fast_model", "local_fast_url"),
    ("deep", "sensitive"): ("local_deep_model", "local_deep_url"),
}


def _setting_default(key: str) -> str:
    """The ProjectSettings default for a model field.

    A project's config_json only ever holds the fields a user changed - ProjectSettings itself
    is the single source of truth for what an untouched field resolves to. Duplicating those
    defaults as literals here would give them a second place to drift out of sync with Task 1's
    declarations; reading model_fields keeps there being exactly one.
    """
    return ProjectSettings.model_fields[key].default


def _project_setting(slug: str, key: str, default: str) -> str:
    """One value from the project's config_json, falling back to the model default.

    Synchronous, because every caller is: crew factories are built inside a running crew and the
    standalone dispatch is a plain function.
    """
    import contextlib
    import sqlite3
    path = f"{get_settings().database_dir}/{slug}.db"
    with contextlib.suppress(sqlite3.Error, OSError, json.JSONDecodeError):
        with contextlib.closing(sqlite3.connect(path)) as conn:
            row = conn.execute(
                "SELECT config_json FROM projects WHERE slug=?", (slug,)
            ).fetchone()
            if row and row[0]:
                value = json.loads(row[0]).get(key)
                if value:
                    return str(value)
    return default


def get_llm_for_agent(agent_name: str, slug: str) -> LLM:
    """The LLM this agent runs on for this project.

    Raises KeyError for an unregistered agent rather than guessing a tier - an unknown agent is a
    registry gap, and guessing would hide it the way a default tool list would have hidden
    visual_illustrator's missing entry.
    """
    tier = AGENT_TIER[agent_name]
    mode = project_llm_mode(slug)
    settings = get_settings()

    if mode == "sensitive":
        model_key, url_key = _TIER_SETTINGS[(tier, "sensitive")]
        model = _project_setting(slug, model_key, _setting_default(model_key))
        base_url = _project_setting(slug, url_key, _setting_default(url_key))
        if not model or not base_url:
            raise LocalModelUnavailable(
                f"Project '{slug}' is sensitive and has no local model for the '{tier}' tier. "
                f"Set {model_key} and {url_key} in the project's settings. "
                f"A hosted model is never substituted for a sensitive project."
            )
        return LLM(
            model=f"openai/{model}",
            base_url=base_url,
            api_key="not-needed",
            max_tokens=_MAX_TOKENS,
        )

    model_key, _ = _TIER_SETTINGS[(tier, "standard")]
    model = _project_setting(slug, model_key, _setting_default(model_key))
    return LLM(
        model=model,
        api_key=settings.anthropic_api_key,
        max_tokens=_MAX_TOKENS,
        **_LONG_CALL_TRANSPORT,
    )
