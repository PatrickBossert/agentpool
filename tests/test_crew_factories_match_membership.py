# tests/test_crew_factories_match_membership.py
"""A declaration is not a dispatch.

`test_crew_membership.py` checks that the three declarations of crew membership agree -
`_CREW_AGENT_NAMES` in the backend and two maps in the frontend. All three can agree while
the factory that actually assembles the crew builds something else entirely, because nothing
compared the factory to the map it claims to implement.

That is not hypothetical: `create_requirements_crew` still built the value chain mapper, left
over from when the crew was called `discovery` and ran before value design. Every membership
declaration said two agents; the factory built three, and running it would have re-run Alex
and overwritten an approved value chain.

Each factory calls `get_tools_for_agent(<agent name>, ...)` once per agent it builds, and that
first argument is in the same string space as `_CREW_AGENT_NAMES` - so patching the registry
records exactly which agents a factory assembles, without constructing an LLM or a tool.
"""
import importlib
import inspect
from unittest.mock import MagicMock, patch

import pytest
from crewai import LLM

from api.services.run_service import _CREW_AGENT_NAMES

# PAM is excluded: it orchestrates crews rather than being one, and its factories are named
# for what they orchestrate rather than for a crew key.
CREW_KEYS = sorted(_CREW_AGENT_NAMES)


def _factory(crew_key: str):
    """`agents.crews.<key>_crew.create_<key>_crew` - asserted, not assumed.

    A factory that does not follow the convention fails here rather than silently escaping
    this test, which is the failure mode of a lookup that skips what it cannot resolve.
    """
    module = importlib.import_module(f"agents.crews.{crew_key}_crew")
    return getattr(module, f"create_{crew_key}_crew")


def _required_args(fn) -> dict:
    """Whatever the signature demands, filled with values inert enough to assemble a crew."""
    args: dict = {}
    for p in inspect.signature(fn).parameters.values():
        if p.default is not inspect.Parameter.empty:
            continue
        if p.name == "run_id":
            args[p.name] = 1
        elif p.name.endswith(("assignments", "labels", "groups")):
            args[p.name] = []
        else:
            args[p.name] = "test"
    return args


@pytest.mark.parametrize("crew_key", CREW_KEYS)
def test_the_factory_builds_exactly_the_agents_the_crew_declares(crew_key):
    factory = _factory(crew_key)
    module = importlib.import_module(f"agents.crews.{crew_key}_crew")

    built: list[str] = []

    def record(agent_name, *args, **kwargs):
        built.append(agent_name)
        return []

    with patch.object(module, "get_tools_for_agent", side_effect=record):
        factory(llm=MagicMock(spec=LLM), **_required_args(factory))

    # Compared as sets: which agents run is the fact under test, and the order a factory
    # constructs them in is not the order its tasks run in.
    assert set(built) == set(_CREW_AGENT_NAMES[crew_key])
    # And as a count, so a factory building the same agent twice does not pass on set equality.
    assert len(built) == len(_CREW_AGENT_NAMES[crew_key])
