# tests/test_requirement_levels.py
"""Two levels of requirement, two keys.

Casey identifies **strategic requirements** - the challenges and opportunities in value chain
activity or maturity that the organisation must address to unlock value. Sam and Riley
enumerate the **change requirements** that deliver the capability uplift initiatives Sage
defines. Different levels, different evidence, different consumers.

They shared the key `requirements`. Casey wrote it at step 4, Sage read it at step 6 and got
the strategic set, and Riley overwrote it at step 7 - so the roadmap and the business plan read
that key at steps 8 and 9 and got change requirements, with the strategic set destroyed. Live
data loss on every full pipeline run, reported nowhere.

The tests below assert the general property as well as this instance: a state key with two
writers is a slot whose contents depend on run order, and this is the second one found.
"""
from __future__ import annotations

import collections
import re
from pathlib import Path

import pytest

from api.services.run_service import _CREW_AGENT_NAMES

AGENTS = Path(__file__).resolve().parent.parent / "agents"
_ADJACENT_LITERALS = re.compile(r'"\s*\n\s*"')

DISPATCHED = {agent for agents in _CREW_AGENT_NAMES.values() for agent in agents}


def _joined(path: Path) -> str:
    """Source with adjacent string literals joined.

    A write instruction spans two literals - the key on one and the agent name on the next -
    so a pattern matching both at once needs them joined first.
    """
    return _ADJACENT_LITERALS.sub("", path.read_text())


def _state_ops(operation: str) -> list[tuple[str, str, str]]:
    """Every (key, agent_name, module) triple for reads or writes across the agent modules."""
    found = []
    for path in sorted(AGENTS.rglob("*.py")):
        if path.relative_to(AGENTS).parts[0] in ("tools", "crews"):
            continue
        for key, agent in re.findall(
            rf"operation='{operation}', key='([a-z0-9_]+)',\s*agent_name='([a-z0-9_]+)'",
            _joined(path),
        ):
            found.append((key, agent, path.name))
    return found


def _writers() -> dict[str, set[str]]:
    writers: dict[str, set[str]] = collections.defaultdict(set)
    for key, agent, _ in _state_ops("write"):
        writers[key].add(agent)
    return writers


def _readers_of(key: str) -> set[str]:
    return {agent for k, agent, _ in _state_ops("read") if k == key}


def test_the_scan_finds_the_writes_it_is_asserting_over():
    """An empty or truncated scan would make every assertion below pass over nothing.

    The literal-joining and the regex are both fragile to a reformat, and a silent zero is the
    failure mode that looks like success.
    """
    writers = _writers()
    assert len(writers) >= 15, f"only {len(writers)} write keys found - the scan has drifted"
    assert "strategic_requirements" in writers
    assert "requirements_analysis" in writers


def test_no_output_key_has_two_writers():
    """The general form. A key two agents write is a slot whose contents depend on run order,
    and the loser's work is destroyed with no error anywhere.

    Scoped to agents some crew actually dispatches. `interview_script_designer` also writes
    `interview_scripts`, but it is Maya's predecessor - present in the tool registry and in no
    crew - so nothing runs it and it cannot collide with anything at runtime. Naming the
    exclusion here rather than filtering it silently: if that module is ever wired into a crew,
    this test starts failing, which is the correct moment to notice.
    """
    collisions = {
        key: sorted(agents & DISPATCHED)
        for key, agents in _writers().items()
        if len(agents & DISPATCHED) > 1
    }
    assert collisions == {}, f"keys written by more than one dispatched agent: {collisions}"


def test_casey_writes_strategic_requirements():
    assert _writers()["strategic_requirements"] == {"synthesis_analyst"}


def test_riley_writes_requirements_analysis():
    assert _writers()["requirements_analysis"] == {"requirements_analyst"}


def test_no_agent_touches_the_bare_requirements_key():
    """Reads as well as writes. A reader left pointing at the retired key gets nothing back and
    analyses an empty set rather than failing, which is the silent kind of wrong."""
    stale = [(k, a, m) for k, a, m in _state_ops("write") + _state_ops("read") if k == "requirements"]
    assert stale == [], f"still using the retired bare key: {stale}"


def test_sage_derives_initiatives_from_the_strategic_level():
    """Sage runs at step 6, before Riley writes anything at step 7. Pointing him at the change
    requirements would have him read a key nothing has written yet."""
    assert "initiative_identifier" in _readers_of("strategic_requirements")


def test_quinn_builds_propositions_from_the_strategic_level():
    # Step 5, also before Riley runs. Same reasoning as Sage.
    assert "value_proposition_generator" in _readers_of("strategic_requirements")


def test_the_business_plan_reads_both_levels_by_name():
    """It runs last and is the one consumer that genuinely wants both - the strategic framing
    and the delivery detail. Reading one key and getting whichever ran last is what this split
    exists to end."""
    readers = _state_ops("read")
    keys = {k for k, agent, _ in readers if agent == "business_plan_generator"}
    assert {"strategic_requirements", "requirements_analysis"} <= keys


@pytest.mark.parametrize("key", ["strategic_requirements", "requirements_analysis"])
def test_each_level_is_read_by_someone(key):
    """A level nothing reads is a level being produced for nobody, which would make the split
    an accounting exercise rather than a fix."""
    assert _readers_of(key), f"nothing reads {key}"
