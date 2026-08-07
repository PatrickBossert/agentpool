# tests/test_crew_agent_registration.py
"""Every agent a crew dispatches must have tools, or the crew cannot be built at all.

`get_tools_for_agent` raises `ValueError: Unknown agent` for a name absent from its
`tool_map`, and the crew factories call it while assembling - so a missing entry is not a
degraded crew, it is a crew that raises before its first task. `create_business_plan_crew`
does exactly that today.

Nothing caught it. tests/test_business_plan_crew.py builds the crew four times, but every
one of those tests patches `get_tools_for_agent` out, which is the correct thing for a
wiring test to do and the reason none of them can see this. The gap is only visible from
outside, against the real registry - which is what this file is.
"""
import pytest

from api.services.run_service import _CREW_AGENT_NAMES
from agents.tools.registry import get_tools_for_agent


# Known-unregistered agents, pinned deliberately rather than skipped.
#
# The Illustrator is planned work whose upstream outputs do not exist yet, so registering
# tools for him now would buy a crew that builds and then fails further in. Pinning him
# here keeps the default suite green while stating the defect in a place that breaks when
# it changes: add an unregistered agent and this test fails; register the Illustrator and
# it also fails, asking whoever fixed it to delete this set.
KNOWN_UNREGISTERED: frozenset[str] = frozenset({"visual_illustrator"})


def _unresolved() -> set[str]:
    """Agent names the registry cannot supply tools for.

    Construction is offline and costs about a second for the whole map - the tools hold
    slug and run_id, and none of them open a database or a socket until they are used.
    """
    missing: set[str] = set()
    for agent_names in _CREW_AGENT_NAMES.values():
        for name in agent_names:
            try:
                get_tools_for_agent(name, slug="x", run_id=1, sector="test")
            except ValueError:
                missing.add(name)
    return missing


def test_every_dispatched_agent_resolves_in_the_registry():
    """Asserted as a set equality, not a subset.

    `<=` would pass while the Illustrator stayed broken forever, and pass again if someone
    quietly fixed him. Equality is what makes both directions of change visible.
    """
    assert _unresolved() == set(KNOWN_UNREGISTERED), (
        "Crew agents whose registry entry is missing have changed. If you registered "
        "visual_illustrator, remove it from KNOWN_UNREGISTERED. If a new name appears, "
        "its crew now raises ValueError before running - add the tools, do not add the name."
    )


def test_the_business_plan_crew_cannot_be_built_while_the_illustrator_is_unregistered():
    """The consequence, stated where it happens.

    The test above names a registry gap; this one shows what that gap costs, so the fix is
    not mistaken for bookkeeping. Delete this test when the Illustrator is registered - a
    crew that builds will make it fail.
    """
    from unittest.mock import MagicMock
    from crewai import LLM
    from agents.crews.business_plan_crew import create_business_plan_crew

    with pytest.raises(ValueError, match="Unknown agent: visual_illustrator"):
        create_business_plan_crew(
            slug="x", run_id=1, llm_mode="standard", sector="logistics",
            llm=MagicMock(spec=LLM),
        )
