# api/services/health_types.py
"""The two shapes a health check deals in, in a module that imports nothing of ours.

They lived in `health_checks.py`, which is where they read most naturally - and that made a
cycle the moment a probe lived anywhere else: `health_checks` imports the probe modules to
build its registry, and each probe module imports `HealthResult` back.

**The cycle did not fail; it degraded, which was worse.** `HEALTH_CHECKS` was assembled behind
a `try/except ImportError`, so the registry silently had three members when `health_checks` was
imported first and one when `provider_quota` was - an alert path whose membership depended on
which module a caller happened to touch first. Two of the three checks simply did not exist,
and nothing said so.

Types with no dependencies of their own break it structurally, so no guard is needed and no
import order can change what the registry contains.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class HealthResult:
    """Whether a dependency is working, and the operator's sentence if it is not.

    **Three states, not two, and the third is the one this product actually lives in.** Two of
    the four providers cannot be read at all with the keys this deployment holds - ElevenLabs'
    allowance needs `user_read`, Deepgram's balance needs Admin - so "I looked and it is fine"
    and "I could not look" are both routine, and they are not the same answer.

    `ok=True, degraded=True` was the shape that made this necessary: a reader that could not see
    a quota reported **healthy** while its own diagnosis said, honestly, that it had read
    consumption rather than an allowance. The prose was right and the boolean was wrong, and the
    boolean is what a consumer renders. The first thing to draw a green light from this would
    have shown ElevenLabs green while nothing had read its allowance - the *"a default and a
    write are indistinguishable"* trap in CLAUDE.md, one field along.

    So `ok` now means what it says - **this dependency is known to be working** - and a reader
    that could not see the thing it checks answers `ok=False, degraded=True`. `degraded`
    separates "cannot see" from "looked, and it is bad", because the remedies differ: one is a
    key permission to widen, the other is a balance to top up. A consumer that does not know
    about `degraded` still fails safe, which is the direction that matters.
    """

    ok: bool
    diagnosis: str = ""
    degraded: bool = False

    @property
    def failed(self) -> bool:
        """Known to be broken, as opposed to merely unreadable."""
        return not self.ok and not self.degraded


@dataclass(frozen=True)
class HealthCheck:
    """One declared dependency of this deployment.

    `key` is the incident key the delivery seam rate-limits on. `probe` answers whether the
    thing is working *now*; it is called at the moment of a real failure to tell an operator
    which kind of failure it was, and deliberately not on a timer.

    Every probe takes a slug even when the thing it checks is a property of the account rather
    than of a project - a quota is per account, a vector store is per project's grants - so the
    caller can hand every member the failing project's slug without knowing which is which.
    """

    key: str
    label: str
    probe: Callable[[str], HealthResult]
