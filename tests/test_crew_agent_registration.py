# tests/test_crew_agent_registration.py
"""Every agent a crew dispatches must have tools, or the crew cannot be built at all.

`get_tools_for_agent` raises `ValueError: Unknown agent` for a name absent from its
`tool_map`, and the crew factories call it while assembling - so a missing entry is not a
degraded crew, it is a crew that raises before its first task. `create_business_plan_crew`
did exactly that, on master, for as long as the Illustrator was wired into it.

Nothing caught it. tests/test_business_plan_crew.py builds the crew four times, but every
one of those tests patches `get_tools_for_agent` out, which is the correct thing for a
wiring test to do and the reason none of them can see this. The gap is only visible from
outside, against the real registry - which is what this file is.
"""
from api.services.run_service import _CREW_AGENT_NAMES
from agents.tools.registry import get_tools_for_agent


# Known-unregistered agents. Empty, and meant to stay that way.
#
# It held visual_illustrator until his tools were registered - the equality assertion below
# is what reported the fix, by failing the moment he resolved. Anything added here needs the
# same exit condition written down beside it: what makes it leave.
KNOWN_UNREGISTERED: frozenset[str] = frozenset()


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
        "Crew agents whose registry entry is missing have changed. A new name here means "
        "that crew now raises ValueError before running - add the tools, do not add the "
        "name to KNOWN_UNREGISTERED unless you also write down what makes it leave."
    )


def test_every_dispatched_crew_agent_resolves_to_a_skills_name():
    """The same question asked of the other registry an agent has to be in.

    `_fetch_skill_notes` looks each dispatched agent up in `_SNAKE_TO_DISPLAY` to find the
    name `agent_skills` is keyed by, and skips it when there is none. Absence is silent in
    **both** directions: the agent receives no library skills however many are approved for
    it, and a proposal about that agent can be reviewed, approved, and still reach no prompt.

    `visual_illustrator` was missing from that map for as long as he had been dispatched -
    the second registry he was absent from, after the tool map the test above exists for -
    and nothing here or anywhere else was comparing the two. `second_interviewer` was the
    first agent added since, and this is the check that would have caught either.

    Asserted as an inclusion rather than an equality, because the two maps genuinely differ:
    `_SNAKE_TO_DISPLAY` may name an agent no crew currently dispatches without anything
    breaking, while a dispatched agent absent from it silently loses its skills.
    """
    from api.services.run_service import _SNAKE_TO_DISPLAY

    dispatched = {a for agents in _CREW_AGENT_NAMES.values() for a in agents}
    missing = sorted(dispatched - set(_SNAKE_TO_DISPLAY))
    assert not missing, (
        f"{missing} are dispatched by a crew and have no entry in _SNAKE_TO_DISPLAY, so no "
        f"approved skill or note can ever reach them - and nothing says so at run time."
    )
