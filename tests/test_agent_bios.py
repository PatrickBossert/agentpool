# tests/test_agent_bios.py
"""A bio is what a reader uses to decide whether an agent is doing its job.

`AGENT_ROLE` in agentStatus.ts is shown in the agent panel, and the agent modules carry the
role, goal and task the agent actually runs under. The re-sequencing moved two agents and
renamed two crews, which left four bios describing work that has moved or changed - and a bio
that describes the old job is worse than no bio, because a reader compares the output against
it and concludes the agent misbehaved.

Every assertion here is on the phrase that is now WRONG rather than on the presence of a new
one. Adding a sentence while leaving the stale one beside it is the likely half-fix, and it
passes the other form.

AGENT_ROLE is parsed from the TypeScript rather than duplicated, following
tests/test_crew_output_types.py - a fixture copy would be a second declaration of the fact
under test.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AGENT_STATUS_TS = REPO / "ui" / "src" / "components" / "agentStatus.ts"


def _agent_role() -> dict[str, str]:
    source = AGENT_STATUS_TS.read_text()
    block = re.search(r"export const AGENT_ROLE: Record<string, string> = \{(.*?)\n\}",
                      source, re.S)
    assert block, f"AGENT_ROLE not found in {AGENT_STATUS_TS} - has it been renamed?"
    pairs = re.findall(r"'([^']+)':\s*'((?:[^'\\]|\\.)*)'", block.group(1))
    roles = {name: body.replace("\\'", "'") for name, body in pairs}
    # A parse that silently returned {} would make every "phrase is absent" assertion below
    # pass vacuously - the exact failure this file exists to prevent.
    assert len(roles) > 10, f"parsed only {len(roles)} roles - the parser has drifted"
    return roles


def _module(path: str) -> str:
    return (REPO / path).read_text()


# ── Morgan: document hypotheses, not discovery findings ───────────────────────

def test_morgans_bio_no_longer_claims_she_works_from_discovery_findings():
    assert "discovery findings" not in _agent_role()["Value Lever Analyst"]


def test_morgans_task_frames_her_output_as_hypotheses():
    """Levers read out of documents are what the organisation claims to care about. If Maya
    treats them as established, the interviews anchor on them and lose the ability to
    contradict them - and the value of Casey's themes is that they come from what people
    actually said."""
    source = _module("agents/discovery/value_lever_analyst.py")
    assert "hypothes" in source.lower()


def test_morgan_no_longer_reads_a_requirements_register_that_does_not_exist_yet():
    # She runs first now. `requirements` is written by Riley in the seventh crew, so reading
    # it would return nothing and she would invent levers from an empty input rather than
    # fail - the silent kind of wrong.
    source = _module("agents/discovery/value_lever_analyst.py")
    assert "key='requirements'" not in source


# ── Sam: initiative-scoped enumeration, not an open interview ────────────────

def test_sams_output_key_no_longer_reads_as_a_stakeholder_interview():
    """`interview_transcript` is one of Avery's artefacts by every reading of the name. Sam
    running seventh against existing initiatives produces a requirements capture, and two
    unrelated things under one name is how a reader ends up looking at the wrong artefact."""
    source = _module("agents/discovery/requirements_capture.py")
    assert "key='interview_transcript'" not in source


def test_whoever_reads_sams_output_reads_the_key_he_writes():
    """The rename is only safe if the reader moved with it. Riley reads Sam's output, and a
    reader still pointed at the old key gets nothing back and analyses an empty set."""
    # Anchored on operation='write': every read line in the same task has the identical
    # `key=..., agent_name='requirements_capture'` shape, so a looser pattern pins Riley to
    # whichever key Sam happens to read first.
    written = re.search(r"operation='write', key='([a-z_]+)'",
                        _module("agents/discovery/requirements_capture.py"))
    assert written, "could not find the key requirements_capture writes"
    assert f"key='{written.group(1)}'" in _module("agents/discovery/requirements_analyst.py")


def test_sams_bio_no_longer_describes_an_open_dialogue_with_the_project_team():
    assert "structured dialogue with the project team" not in _agent_role()["Requirements Capture"]


# ── Casey: themes, and not another crew's registers ──────────────────────────

def test_casey_no_longer_writes_morgans_value_levers():
    """Morgan now runs first and Casey fourth, so Casey's write lands on top of hers. Her
    levers are what Maya designed the instruments against and what a reviewer approved;
    overwriting them silently discards both."""
    source = _module("agents/discovery/synthesis_analyst.py")
    assert "key='value_levers'" not in source


def test_caseys_goal_no_longer_claims_a_value_lever_register():
    source = _module("agents/discovery/synthesis_analyst.py")
    assert "value lever register" not in source


def test_caseys_bio_names_the_two_kinds_of_theme_he_owns():
    """The one place a positive assertion is right: horizontal and vertical are a distinction
    a reader cannot infer from the absence of anything."""
    role = _agent_role()["Synthesis Analyst"].lower()
    assert "horizontal" in role and "vertical" in role


# ── Drew and Sage: capabilities, not architecture ────────────────────────────

def test_drews_bio_no_longer_claims_he_designs_a_target_architecture():
    """His own task extracts the current state from documents. The panel said he designs the
    architecture required to deliver the portfolio - the opposite direction of work."""
    role = _agent_role()["Enterprise Architect"]
    assert "Designs the enterprise architecture" not in role
    assert "Mermaid" not in role


def test_sages_bio_no_longer_decomposes_an_architecture_blueprint():
    # There is no blueprint. He reads the as-is capability register and the propositions, and
    # derives the initiatives that close the gap between them.
    assert "architecture blueprint" not in _agent_role()["Initiative Identifier"]


# ── The one that must not change ─────────────────────────────────────────────

RILEYS_BIO = (
    'Analyses the captured requirement set for completeness, consistency, priority, and '
    'hidden conflicts. Reads client documents to surface implicit requirements that the '
    'direct session may have missed, and queries the knowledge base for related precedents. '
    'Produces a structured, prioritised requirement analysis that forms the foundation for '
    'value lever identification.'
)


def test_rileys_bio_is_untouched():
    """Riley analyses a captured requirement set for completeness, consistency and conflict.
    That work is unchanged; only its inputs and its turn moved.

    Pinned so the distinction is deliberate. A re-sequencing that quietly rewrote every bio
    would lose the difference between an agent whose job changed and one whose turn moved,
    and nothing else in this file would notice.
    """
    assert _agent_role()["Requirements Analyst"] == RILEYS_BIO
