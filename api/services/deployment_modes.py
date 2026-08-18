# api/services/deployment_modes.py
"""What each deployment mode is *permitted* to do with a project's material.

Egress is a grant, never an assumption. Four places decide whether a project's material may
leave the premises - the Chroma client, the crew LLM, the non-crew completion, and the
auditor-facing privacy view - and every one of them used to ask `mode == "sensitive"` and hand
everything else the off-premises branch. That shape is safe for exactly as long as nobody adds
a mode. `api/models.py` already declares three (`standard`, `sensitive`, `fallback`), so the
binary was already a simplification, and a fourth - sovereign: hosted models, a local vector
store - is planned. Adding it to the enum and forgetting one of the four sites would send that
client's corpus to Chroma Cloud with no error and no warning. CLAUDE.md names this shape
elsewhere: *"forgetting fails unsafe, not loudly"*.

So the question is inverted. A mode holds a set of capabilities, and a site asks whether the
capability it is about to use is in that set. **A mode absent from the table holds nothing** -
its data stays local and hosted inference is refused - so the cost of forgetting is a project
that will not run rather than a project that leaks.

| Mode | `CLOUD_VECTOR_STORE` | `HOSTED_INFERENCE` |
|---|---|---|
| `standard` | yes | yes |
| `fallback` | yes | yes |
| `sensitive` | no | no |
| anything else | no | no |

**On the default.** `_EGRESS_GRANTS.get(mode, frozenset())` is a `.get()` with a default, and
this branch has just spent a task deleting one - `ChromaQueryTool`'s
`.get(collection, f"sector_{self.sector}")`, which made the store shared across every
engagement in a sector the answer to any name the dict did not hold. These are not the same
thing, and the difference is the whole point: **that default fell towards disclosure, this one
falls towards containment.** A default is not a defect; a default pointing the wrong way is.
Nothing here may ever acquire a default that grants something.

Unknown modes are logged rather than raised, matching `project_llm_mode`'s own
fail-closed-and-warn behaviour in `chroma_client.py`. Raising would take a whole project down
over a hand-edited value in one column; default-deny keeps the data local and lets the
hosted-inference path refuse on its own terms, with its own sentence.

This module owns *mode* vocabulary. `api/services/knowledge_tiers.py` owns *tier* vocabulary -
how wide a store is, and who may write it. They answer different questions and must not be
merged: a tier says which collection, a mode says whether that collection may live off the
premises.

**This is not where a fourth mode is added.** Adding `sovereign` means adding a row here *and*
a value to both `Literal`s in `api/models.py` - and the two are held equal by
`tests/test_deployment_modes.py`, so adding it in one place alone fails a test rather than a
client.
"""
from __future__ import annotations

import logging
from enum import Enum

_log = logging.getLogger(__name__)


class Capability(Enum):
    """One thing a mode may be permitted to do with the project's material.

    The value is the sentence an operator or an auditor reads, so it says what travels rather
    than naming the mechanism.
    """

    CLOUD_VECTOR_STORE = "may store vectors and documents in Chroma Cloud"
    HOSTED_INFERENCE = "may send prompts to a hosted model provider"


_EVERYTHING = frozenset(Capability)
_NOTHING: frozenset[Capability] = frozenset()

# Every declared mode, and what it is permitted to do. Written out per mode rather than as
# "sensitive is the strict one and the rest are open", because the second form is the defect:
# it makes every future mode open by omission.
EGRESS_GRANTS: dict[str, frozenset[Capability]] = {
    "standard": _EVERYTHING,
    # `fallback` has never had routing of its own - it resolves exactly as `standard` does
    # everywhere in the codebase. Stated here rather than left to fall through the default, so
    # that "this mode sends material off the premises" is a thing somebody wrote down.
    "fallback": _EVERYTHING,
    "sensitive": _NOTHING,
}


def granted_to(mode: str) -> frozenset[Capability]:
    """What this mode may do. An unrecognised mode may do nothing, and says so in the log."""
    grants = EGRESS_GRANTS.get(mode)
    if grants is None:
        _log.warning(
            "deployment mode %r is not declared in EGRESS_GRANTS - granting it no egress at "
            "all, so this project's material stays on this deployment and hosted inference "
            "is refused. Declared modes are: %s.",
            mode,
            ", ".join(sorted(EGRESS_GRANTS)),
        )
        return _NOTHING
    return grants


def permits(mode: str, capability: Capability) -> bool:
    """Whether a project in this mode may do `capability`.

    The one question the four egress sites ask. Never phrase it as a comparison against a mode
    name at the call site - that is the shape this module exists to end.
    """
    return capability in granted_to(mode)
