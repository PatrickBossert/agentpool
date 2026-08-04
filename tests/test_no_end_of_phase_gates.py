# tests/test_no_end_of_phase_gates.py
"""A crew's last act is finishing.

Approval is recorded in approval_commits, outside the run. An agent instructed to call
HumanInputTool and wait for "approved" blocks for up to 24 hours and then proceeds on
the string "timeout" as though it had an answer.
"""
import re
from pathlib import Path

import pytest

_ADJACENT_LITERALS = re.compile(r'"\s*\n\s*"')

AGENTS_ROOT = Path("agents")

# agents/tools/ is the gate mechanism itself (HumanInputTool lives there) and
# agents/crews/ only imports HumanInputTool for tool registration, not to gate
# on it. Everything else under agents/ is a candidate agent module.
_EXCLUDED_DIRS = {"tools", "crews"}


def _join_adjacent_literals(text: str) -> str:
    """Join adjacent Python string literals so a phrase split across them is searchable.

    A prompt written across two literals hides the phrase we search for - the closing
    quote, the newline, and the indentation all sit between "call " and the tool name.
    Two modules do this (enterprise_architect, synthesis_analyst), which is why a raw
    substring check missed them on this file's first pass.
    """
    return _ADJACENT_LITERALS.sub("", text)


def _discover_agent_modules() -> list[str]:
    """Every module under agents/, excluding the tool and crew directories.

    This walks the filesystem instead of naming modules by hand. A hand-written list
    is exactly what let two gated modules (portfolio_manager, interaction_designer)
    go unchecked: the plan enumerated twelve names and the list was wrong. Discovery
    catches a gate added to any agent module, including one that does not exist yet.
    """
    modules = []
    for path in sorted(AGENTS_ROOT.rglob("*.py")):
        relative = path.relative_to(AGENTS_ROOT)
        if relative.parts[0] in _EXCLUDED_DIRS:
            continue
        modules.append(str(relative.with_suffix("")))
    return modules


ALL_AGENT_MODULES = _discover_agent_modules()

# These use the tool to ask a question, not to seek a sign-off. They are project 5's
# problem, and removing them here would silently disable the interview path. This is
# a deliberate exception list, not something to (re-)discover, so it stays hand-written -
# but test_the_allow_list_names_modules_that_exist keeps it honest against typos, and
# test_the_genuine_uses_survive keeps it honest against silent deletion.
#
# discovery/requirements_capture left this list when the crews were re-sequenced. His
# genuine use WAS the multi-turn dialogue: running before value design, an open interview
# with the project team was the only input he had. Running seventh against an initiative
# register, the job is enumeration against a defined scope, so the dialogue went and the
# tool with it. He is now checked for gate phrases like everything else, which is stricter
# than the exception he used to hold - the entry is removed because the use genuinely
# ended, not to make a test pass.
KEEPS_A_GENUINE_USE = [
    "discovery/stakeholder_interviewer",
    "business_plan/business_plan_generator",
]

# Every discovered agent module except the deliberate exceptions above must contain
# neither gate phrase. Because ALL_AGENT_MODULES comes from a filesystem walk, this
# list grows automatically when a module is added - nobody has to remember to.
CHECKED_FOR_GATES = [m for m in ALL_AGENT_MODULES if m not in KEEPS_A_GENUINE_USE]


def _source(module: str) -> str:
    """Source with adjacent string literals joined, so a phrase split across a line
    break in the Python source is still visible to a plain substring search."""
    raw = Path("agents", f"{module}.py").read_text()
    return _join_adjacent_literals(raw)


def test_join_adjacent_literals_reveals_a_split_phrase():
    """Prove the normaliser actually joins what a raw read would keep apart."""
    split_source = (
        '            "revise and call "\n'
        '            "HumanInputTool again.\\n"\n'
    )
    assert "call humaninputtool again" not in split_source.lower()
    assert "call humaninputtool again" in _join_adjacent_literals(split_source).lower()


def test_discovery_finds_a_realistic_number_of_modules():
    """An empty or truncated discovery list would make every assertion below pass
    vacuously - over nothing - which is worse than not having the assertions at all."""
    assert len(ALL_AGENT_MODULES) >= 20


def test_the_allow_list_names_modules_that_exist():
    """A typo'd entry in KEEPS_A_GENUINE_USE would silently exempt nothing and be
    checked by nothing - catch that here rather than let it disappear quietly."""
    for module in KEEPS_A_GENUINE_USE:
        assert module in ALL_AGENT_MODULES, f"{module} is not a discovered agent module"


@pytest.mark.parametrize("module", CHECKED_FOR_GATES)
def test_no_module_asks_the_reviewer_to_reply_approved(module):
    """The gate's signature phrase, whatever wording surrounds it."""
    source = _source(module).lower()
    assert 'reply "approved"' not in source and "reply 'approved'" not in source, (
        f"{module} still gates on a typed approval"
    )


@pytest.mark.parametrize("module", CHECKED_FOR_GATES)
def test_no_module_loops_on_revision_notes(module):
    source = _source(module).lower()
    assert "call humaninputtool again" not in source, (
        f"{module} still loops waiting for revisions"
    )


@pytest.mark.parametrize("module", KEEPS_A_GENUINE_USE)
def test_the_genuine_uses_survive(module):
    """business_plan_generator appears in both lists deliberately: its gate goes and
    its context-gathering step stays, which a per-file count could not express."""
    assert "HumanInputTool" in _source(module), (
        f"{module} lost a use that is not an approval gate"
    )


def test_the_tool_itself_is_untouched():
    source = Path("agents/tools/human_input.py").read_text()
    assert "class HumanInputTool" in source
    assert "time.sleep" in source
