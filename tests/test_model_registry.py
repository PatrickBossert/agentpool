# tests/test_model_registry.py
"""The registry is the single place an agent's model is decided.

Crew factories previously chose models themselves, which is how discovery_interviews_crew came
to declare llm_mode and never read it - putting the Synthesis Analyst on a hosted model while
it held ChromaQueryTool over the project's own interview answers.
"""
import json
import re
import sqlite3
from pathlib import Path

import pytest

from api.config import get_settings


@pytest.fixture
def two_projects(tmp_path, monkeypatch):
    """One sensitive, one standard, in the same process.

    A per-deployment implementation passes every single-project test and fails only this shape.
    """
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    for slug, mode in (("sec-proj", "sensitive"), ("std-proj", "standard")):
        conn = sqlite3.connect(tmp_path / f"{slug}.db")
        conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, "
                     "llm_mode TEXT, sector TEXT, config_json TEXT)")
        conn.execute("INSERT INTO projects (slug, llm_mode, sector, config_json) VALUES (?,?,?,?)",
                     (slug, mode, "test", json.dumps({})))
        conn.commit(); conn.close()
    from api.services import chroma_client
    chroma_client._MODE_CACHE.clear()
    yield
    get_settings.cache_clear()


def _set_config(tmp_path, slug: str, config: dict) -> None:
    """Write config_json the way PATCH /projects/{slug}/settings would - the way a user
    actually reaches this table, as opposed to monkeypatching model_registry internals."""
    conn = sqlite3.connect(tmp_path / f"{slug}.db")
    conn.execute("UPDATE projects SET config_json=? WHERE slug=?", (json.dumps(config), slug))
    conn.commit()
    conn.close()


def test_every_dispatched_agent_has_a_tier():
    """Set equality, not a subset. A subset passes forever while an agent has no tier, and
    passes again if one is removed. This is the shape that caught visual_illustrator missing
    from the tool registry, where the crew raised before its first task."""
    from agents.model_registry import AGENT_TIER
    src = Path("agents/tools/registry.py").read_text()
    body = src.split("tool_map: dict[str, list[BaseTool]] = {")[1]
    registered = set(re.findall(r'^\s{8}"([a-z_]+)":', body, re.M))
    assert set(AGENT_TIER) == registered, (
        f"only in tool registry: {registered - set(AGENT_TIER)}; "
        f"only in AGENT_TIER: {set(AGENT_TIER) - registered}"
    )


def test_tiers_are_only_fast_or_deep():
    from agents.model_registry import AGENT_TIER
    assert set(AGENT_TIER.values()) <= {"fast", "deep"}


def test_a_sensitive_project_gets_local_models_for_both_tiers(two_projects):
    from agents.model_registry import get_llm_for_agent
    fast = get_llm_for_agent("stakeholder_interviewer", "sec-proj")
    deep = get_llm_for_agent("synthesis_analyst", "sec-proj")
    assert fast.base_url == "http://localhost:11434/v1"
    assert deep.base_url == "http://localhost:11434/v1"
    assert "claude" not in f"{fast.model}{deep.model}"


def test_both_modes_are_honoured_in_one_process(two_projects):
    """The test a per-deployment switch cannot pass."""
    from agents.model_registry import get_llm_for_agent
    assert get_llm_for_agent("synthesis_analyst", "sec-proj").base_url is not None
    assert get_llm_for_agent("synthesis_analyst", "std-proj").base_url is None


def test_two_agents_in_one_crew_get_different_models(two_projects):
    """The collapse being fixed: value_design_crew gave both agents one model in sensitive mode."""
    from agents.model_registry import get_llm_for_agent
    fast = get_llm_for_agent("portfolio_manager", "std-proj")
    deep = get_llm_for_agent("value_proposition_generator", "std-proj")
    assert fast.model != deep.model


def test_a_deliberately_blanked_local_tier_refuses_rather_than_falling_back(two_projects, tmp_path):
    """Never a hosted fallback, and never borrowing the other tier.

    Drives a real blank value in config_json, written the way PATCH /projects/{slug}/settings
    would write it - local_deep_model is a plain `str` with no `min_length`, so a user can clear
    it from the UI. This is the load-bearing version: a fix that made _project_setting return
    the untouched default for a *present but blank* key (indistinguishable from "never set" under
    a bare `.get(key)` truthiness check) would pass a test that monkeypatches
    _project_setting's return value, because that only proves get_llm_for_agent reacts correctly
    to a falsy input - not that a falsy input is ever reachable from real configuration. It
    wasn't, until _project_setting distinguished absent from blank.
    """
    _set_config(tmp_path, "sec-proj", {"local_deep_model": ""})
    from agents.model_registry import get_llm_for_agent, LocalModelUnavailable
    with pytest.raises(LocalModelUnavailable, match="local_deep_model"):
        get_llm_for_agent("synthesis_analyst", "sec-proj")


def test_get_llm_for_agent_raises_on_a_blank_resolved_value(two_projects, monkeypatch):
    """Unit-level check of the guard itself, decoupled from whether a blank is reachable in
    practice - test_a_deliberately_blanked_local_tier_refuses_rather_than_falling_back is the
    one that proves reachability; this one is kept only for a faster, more targeted signal on
    the raise-and-message behaviour of get_llm_for_agent."""
    from agents import model_registry
    from agents.model_registry import get_llm_for_agent, LocalModelUnavailable
    monkeypatch.setattr(model_registry, "_project_setting",
                        lambda slug, key, default: "" if key == "local_deep_model" else default)
    with pytest.raises(LocalModelUnavailable, match="local_deep_model"):
        get_llm_for_agent("synthesis_analyst", "sec-proj")


def test_a_blank_hosted_model_setting_is_not_silently_defaulted(two_projects, tmp_path):
    """The same absent-vs-blank distinction applies on the standard branch. A blank
    anthropic_deep_model is not a confidentiality leak - the standard branch never touches a
    local model - but _project_setting does not know which branch is calling it, so a fix
    scoped only to the sensitive branch would leave this silently resolving to the untouched
    anthropic/claude-opus-4-6 default instead of failing. crewai.LLM itself refuses an empty
    model string, so with the fix this fails loudly rather than silently choosing a model."""
    _set_config(tmp_path, "std-proj", {"anthropic_deep_model": ""})
    from agents.model_registry import get_llm_for_agent
    with pytest.raises(ValueError, match="non-empty"):
        get_llm_for_agent("synthesis_analyst", "std-proj")


def test_both_llm_paths_set_max_tokens(two_projects):
    """The hosted path set max_tokens=16384 because the 4096 default clips large tool-call JSON.
    The sensitive branch set nothing, so secure mode clipped exactly those outputs."""
    from agents.model_registry import get_llm_for_agent
    for slug in ("sec-proj", "std-proj"):
        llm = get_llm_for_agent("value_chain_mapper", slug)
        assert getattr(llm, "max_tokens", None) == 16384, f"{slug} has no max_tokens"


def test_no_crew_factory_chooses_a_model():
    """Factories ask the registry. A factory that cannot choose a model cannot forget to
    consult llm_mode, which is the defect that shipped past sixteen reviews.

    Guards the class rather than the instance: bare-filename reads recurred across six sites and
    raw database connections across seven before each got a guard.
    """
    offenders = []
    for path in sorted(Path("agents/crews").glob("*_crew.py")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "anthropic/claude" in stripped or "get_pam_llm" in stripped \
                    or "get_haiku_llm" in stripped or "get_crew_llm" in stripped:
                offenders.append(f"{path}:{number}  {stripped[:70]}")
    assert not offenders, (
        "these choose a model instead of asking get_llm_for_agent:\n  " + "\n  ".join(offenders)
    )
