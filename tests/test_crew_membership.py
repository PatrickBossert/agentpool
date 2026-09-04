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

UI_SRC = Path(__file__).resolve().parent.parent / "ui" / "src"
AGENT_STATUS = UI_SRC / "components" / "agentStatus.ts"

# The single front-end module allowed to declare either kind of map, as a path relative to
# ui/src, so the assertion below names a file rather than a variable.
OWNER = "components/agentStatus.ts"


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


# ── No other front-end module may declare either map, whatever it calls them ──
#
# The equality checks above find their maps by name, which is right for the declaration - you
# have to look it up somehow. It is wrong for "and nowhere else": a reviewer added a CREW_TITLE
# carrying the exact stale wording this branch deleted ("Value Chain Mapper", "Architecture",
# "Delivery Planning") plus a CREW_TEAMS crew-to-agents map to Team.tsx, and all 23 tests
# passed, because neither identifier was one anybody had thought to search for.
#
# Five of the ten crew-to-agent maps this branch deleted lived in the front end, so this is
# where an eleventh comes back. Detected by shape, the technique
# tests/test_output_type_labels.py already uses on the same file tree.

_OBJECT_LITERAL = re.compile(r"=\s*\{")
_ENTRY = re.compile(r"(\w+)\s*:\s*(\[[^\]]*\]|'[^']*')")


def _balanced(text: str, opening: int) -> str:
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1:index]
    return ""


def _crew_keyed_literals(source: str) -> list[dict[str, str]]:
    """Every object literal in the source that is *about* crews.

    Two crew ids, and crew ids as at least half the keys. The second half of that is what
    keeps `outputTypeLabels.ts` out: it has `requirements` and `business_plan` among thirty-one
    output types, which are crew ids by coincidence of naming rather than a map of crews. A
    crew map is nearly all crew ids - the ones deleted here were nine of nine and nine of ten.
    """
    crews = set(_CREW_AGENT_NAMES)
    literals = []
    for match in _OBJECT_LITERAL.finditer(source):
        entries = dict(_ENTRY.findall(_balanced(source, source.index("{", match.start()))))
        crew_keys = crews & set(entries)
        if len(crew_keys) >= 2 and len(crew_keys) * 2 >= len(entries):
            literals.append(entries)
    return literals


def _agent_vocabulary() -> set[str]:
    """Every string that names an agent in the front end's own terms.

    The snake ids, plus the role names `AGENT_HUMAN_NAME` is keyed by. Taken from that map
    rather than computed as `id.replace('_', ' ').title()` - the derivation happens to produce
    them, and writing it here would put the coupling Task 2 rejected into a detector where the
    next reader would take it for a rule.
    """
    ids = {agent for agents in _CREW_AGENT_NAMES.values() for agent in agents}
    block = re.search(r"export const AGENT_HUMAN_NAME: Record<string, string> = \{(.*?)\n\}",
                      AGENT_STATUS.read_text(), re.S)
    assert block, "AGENT_HUMAN_NAME not found - the vocabulary would be half empty"
    roles = {role for role, _ in re.findall(r"'([^']+)':\s+'([^']+)'", block.group(1))}
    assert len(roles) == 18, sorted(roles)
    return ids | roles


def _files_declaring(predicate) -> dict[str, int]:
    found: dict[str, int] = {}
    for path in sorted(UI_SRC.rglob("*.ts*")):
        if "__tests__" in path.parts:
            continue
        hits = sum(1 for literal in _crew_keyed_literals(path.read_text()) if predicate(literal))
        if hits:
            found[str(path.relative_to(UI_SRC))] = hits
    return found


def _names_agents(literal: dict[str, str]) -> bool:
    vocabulary = _agent_vocabulary()
    return any(
        value.startswith("[") and any(name in vocabulary for name in re.findall(r"'([^']+)'", value))
        for value in literal.values()
    )


def _labels_crews(literal: dict[str, str]) -> bool:
    """Values that read as prose rather than as keys.

    An uppercase letter and no underscore. That separates 'Value Chain Mapping', 'Requirements'
    and 'PMO' from the snake_case values of the crew-keyed maps that legitimately exist -
    CREW_OUTPUT_TYPE's output types, ReviewDialog's warning codes - without needing to know
    what any of them are.
    """
    return sum(
        1 for value in literal.values()
        if value.startswith("'") and any(c.isupper() for c in value) and "_" not in value
    ) >= 2


def test_the_shape_detector_finds_both_maps_in_the_module_that_owns_them():
    """Guard the guard: a detector matching nothing would excuse every file below."""
    assert _files_declaring(_names_agents).get(OWNER, 0) >= 2, "CREW_AGENT_NAMES and CREW_AGENTS"
    assert _files_declaring(_labels_crews).get(OWNER, 0) >= 1, "CREW_LABELS"


def test_no_other_module_declares_which_agents_a_crew_runs():
    unexpected = {p: n for p, n in _files_declaring(_names_agents).items() if p != OWNER}
    assert not unexpected, (
        f"{sorted(unexpected)} name a crew's agents. Import CREW_AGENTS or CREW_AGENT_NAMES "
        f"from components/agentStatus - a copy here is checked against the backend by nothing, "
        f"which is how one came to file the Value Chain Mapper under `requirements`."
    )


def test_no_other_module_declares_what_a_crew_is_called():
    unexpected = {p: n for p, n in _files_declaring(_labels_crews).items() if p != OWNER}
    assert not unexpected, (
        f"{sorted(unexpected)} label crews. Import CREW_LABELS from components/agentStatus - "
        f"the two copies this branch deleted showed `discovery_mapping` as \"Value Chain "
        f"Mapper\", the agent rather than the crew, and neither knew `assessment_design`."
    )
