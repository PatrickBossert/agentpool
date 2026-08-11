# tests/test_output_ownership.py
"""One owner per output key, enforced where the write happens.

An agent's output instruction lives in its prompt, and a prompt is guidance rather than a
boundary. Maya wrote Alex's value_chain_registry honestly - she declared her own name and
wrote a key that was not hers, because nothing said she could not.
"""
import json

import pytest

from agents.tools.ownership import OUTPUT_OWNERS, check_write


def test_the_owner_may_write_its_own_key():
    assert check_write("value_chain_model", "value_chain_mapper") is None


def test_another_agent_may_not():
    refusal = check_write("value_chain_registry", "interaction_designer")
    assert refusal is not None
    # The message is what the agent reads and acts on. A bare refusal teaches it nothing.
    assert "value_chain_mapper" in refusal


def test_a_key_nobody_owns_is_refused():
    """The batching case. Asserting only the cross-agent case would let
    interview_scripts_batch1 through, which is how nine keys were written that nothing reads,
    nothing validates, and nothing shows for review.

    Asserted against the unowned wording specifically, not merely a refusal: with owner=None,
    the cross-agent branch also refuses and also names the key, so a check that stopped at
    "a refusal happened" would pass whichever branch produced it - including one where the
    unowned guard had quietly stopped running."""
    refusal = check_write("interview_scripts_batch1", "interaction_designer")
    assert refusal is not None
    assert "interview_scripts_batch1" in refusal
    assert "not a declared output" in refusal


def test_every_owner_is_a_real_agent():
    from api.services.run_service import _CREW_AGENT_NAMES

    dispatched = {a for agents in _CREW_AGENT_NAMES.values() for a in agents}
    unknown = {o for o in OUTPUT_OWNERS.values() if o not in dispatched}
    assert unknown == set(), f"keys owned by agents no crew dispatches: {unknown}"


def test_every_declared_write_is_owned_by_the_agent_told_to_make_it():
    """The map is the authority and this holds the prompts to it.

    An instruction telling an agent to write a key it does not own would be refused at run
    time, in a place nobody is watching, after the model has already done the work.
    """
    import collections
    import pathlib
    import re

    join = re.compile(r'"\s*\n\s*"')
    declared = collections.defaultdict(set)
    for path in sorted(pathlib.Path("agents").rglob("*.py")):
        if path.parts[1] in ("tools", "crews"):
            continue
        source = join.sub("", path.read_text())
        for key, agent in re.findall(
            r"operation='write', key='([a-z0-9_]+)',\s*agent_name='([a-z0-9_]+)'", source
        ):
            declared[key].add(agent)

    assert len(declared) >= 15, "the scan found too little to be asserting over"

    from api.services.run_service import _CREW_AGENT_NAMES

    dispatched = {a for agents in _CREW_AGENT_NAMES.values() for a in agents}

    # interview_script_registry finished retiring in this task: the ownership entry was
    # already gone (the ledger it fed is now a database table, maintained as a side effect
    # of the interview_scripts write), and Maya's prompt no longer instructs her to write
    # it either - so the scan below no longer finds the key at all, and the exclusion that
    # covered the gap between those two events is removed rather than left to skip nothing
    # forever.
    assert "interview_script_registry" not in declared, (
        "interview_script_registry should no longer be a declared write - "
        "the instruction to write it was supposed to be removed"
    )

    for key, agents in declared.items():
        for agent in agents & dispatched:
            assert OUTPUT_OWNERS.get(key) == agent, (
                f"{agent} is told to write {key}, owned by {OUTPUT_OWNERS.get(key)}"
            )


def test_the_tool_refuses_a_write_it_does_not_own(tmp_path, monkeypatch):
    """The map existing and the tool consulting it are different facts, and only the second
    protects anything."""
    from api.config import get_settings
    from agents.tools.sqlite_state import SQLiteStateTool

    get_settings.cache_clear()
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()

    tool = SQLiteStateTool(slug="acme", agent_name="interaction_designer")
    result = tool._run(
        operation="write", key="value_chain_registry",
        agent_name="interaction_designer", value=json.dumps({"activities": []}),
    )

    assert "Written to" not in result
    assert "value_chain_mapper" in result
    get_settings.cache_clear()


def test_the_tool_refuses_a_claimed_identity_that_is_not_its_own(tmp_path, monkeypatch):
    from api.config import get_settings
    from agents.tools.sqlite_state import SQLiteStateTool

    get_settings.cache_clear()
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()

    tool = SQLiteStateTool(slug="acme", agent_name="interaction_designer")
    result = tool._run(
        operation="write", key="value_chain_model",
        agent_name="value_chain_mapper", value=json.dumps({}),
    )

    assert "Written to" not in result
    get_settings.cache_clear()


def test_reading_another_agents_key_still_works(tmp_path, monkeypatch):
    """Asserted rather than assumed. A boundary that blocked reads would stop the pipeline
    on its first cross-crew handover."""
    from api.config import get_settings
    from agents.tools.sqlite_state import SQLiteStateTool

    get_settings.cache_clear()
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    outputs = tmp_path / "acme" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "value_chain_model.json").write_text('{"segments": []}')

    tool = SQLiteStateTool(slug="acme", agent_name="interaction_designer")
    result = tool._run(
        operation="read", key="value_chain_model", agent_name="interaction_designer",
    )

    assert "segments" in result
    get_settings.cache_clear()
