# tests/test_crew_membership.py
"""Which agents belong to which crew, declared once and checked everywhere.

A crew's membership is declared in three places - `_CREW_AGENT_NAMES` here in the backend,
and `CREW_AGENT_NAMES` and `CREW_AGENTS` in the frontend. The frontend's own comment says it
mirrors the backend, which is a promise nothing has ever checked. They have drifted.
"""
import re
from pathlib import Path

import pytest

from api.services.run_service import _CREW_AGENT_NAMES

AGENT_STATUS = Path("ui/src/components/agentStatus.ts")


def _frontend_map(name: str) -> dict[str, list[str]]:
    """A crew-to-agents map as the frontend declares it.

    Parsed rather than duplicated: a second copy in a fixture would be a fourth
    declaration of the fact these tests exist to keep singular.
    """
    source = AGENT_STATUS.read_text()
    block = re.search(rf"export const {name}: Record<string, string\[\]> = \{{(.*?)\n\}}",
                      source, re.S)
    assert block, f"{name} not found in {AGENT_STATUS} - has it been renamed?"
    out: dict[str, list[str]] = {}
    for crew, agents in re.findall(r"(\w+):\s*\[([^\]]*)\]", block.group(1)):
        out[crew] = re.findall(r"'([^']+)'", agents)
    return out


def _snake(display: str) -> str:
    return display.lower().replace(" ", "_")


def test_morgan_is_in_the_mapping_crew():
    # Two jobs were conflated. What levers and KPIs does this organisation already talk
    # about is document analysis and belongs early, before Maya designs against them.
    assert "value_lever_analyst" in _CREW_AGENT_NAMES["discovery_mapping"]


def test_morgan_is_in_exactly_one_crew():
    # Asserting only the new home would pass while the agent ran twice per pipeline.
    homes = [c for c, agents in _CREW_AGENT_NAMES.items() if "value_lever_analyst" in agents]
    assert homes == ["discovery_mapping"]


def test_every_agent_belongs_to_exactly_one_crew():
    """The general form of the test above. A move that duplicated any agent is caught here
    whether or not anyone thought to write a test for that particular agent."""
    seen: dict[str, str] = {}
    for crew, agents in _CREW_AGENT_NAMES.items():
        for agent in agents:
            assert agent not in seen, f"{agent} is in both {seen[agent]} and {crew}"
            seen[agent] = crew


def test_the_backend_and_the_frontend_agree_about_membership():
    """CREW_AGENT_NAMES claims to mirror _CREW_AGENT_NAMES. Reading one and asserting
    against a literal proves nothing about the other."""
    assert _frontend_map("CREW_AGENT_NAMES") == _CREW_AGENT_NAMES


def test_the_display_names_agree_with_the_agents_that_run():
    """CREW_AGENTS carries display names for the same crews. It listed a Visual Illustrator
    in delivery that neither dispatch map contained - shown on the org chart, dispatched by
    nothing, which reads to a user as a crew member doing nothing at all."""
    # PAM is excluded deliberately: it is a card on the board and an orchestrator, not a
    # crew build_and_run_crew dispatches, so it belongs in the display map and nowhere in
    # the dispatch one.
    display = {crew: [_snake(a) for a in agents]
               for crew, agents in _frontend_map("CREW_AGENTS").items()
               if crew != "PAM"}
    assert display == _CREW_AGENT_NAMES


def _frontend_labels() -> dict[str, str]:
    """CREW_LABELS as the frontend declares it, parsed rather than duplicated."""
    source = AGENT_STATUS.read_text()
    block = re.search(r"export const CREW_LABELS: Record<string, string> = \{(.*?)\n\}",
                      source, re.S)
    assert block, f"CREW_LABELS not found in {AGENT_STATUS} - has it been renamed?"
    labels = dict(re.findall(r"(\w+):\s*'([^']+)'", block.group(1)))
    # A parse that came back empty would make the comparison below pass vacuously.
    assert len(labels) > 5, f"parsed only {len(labels)} labels - the parser has drifted"
    return labels


def test_the_frontend_and_the_backend_agree_about_crew_labels():
    """A crew's label was declared five times - once in Python and four times in the front
    end - and no two agreed. `discovery_mapping` was "Value Chain Mapping" here, "Value Chain
    Mapper" (the agent) on the dashboard, and "Discovery" in the review dialog.

    PAM is excluded deliberately, as it is from CREW_AGENTS above: it is a card on the board
    and an orchestrator, not a crew anything dispatches.
    """
    from agents.identity import CREW_LABEL

    frontend = {crew: label for crew, label in _frontend_labels().items() if crew != "PAM"}
    assert frontend == CREW_LABEL


def test_pam_is_the_only_thing_the_label_check_excuses():
    """Without this, the cheapest way to make the test above pass is to give a disagreeing
    crew a name the exclusion happens to cover."""
    assert set(_frontend_labels()) - set(_CREW_AGENT_NAMES) == {"PAM"}


def test_every_crew_the_board_orders_has_a_label():
    """CREW_ORDER drives the carousel; a crew ordered without a label renders as a blank
    heading rather than as an error."""
    source = AGENT_STATUS.read_text()
    block = re.search(r"export const CREW_ORDER = \[(.*?)\]", source, re.S)
    assert block, "CREW_ORDER not found - has it been renamed?"
    order = re.findall(r"'([a-z_]+)'", block.group(1))
    assert set(order) <= set(_frontend_labels())
