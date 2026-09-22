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
    """Whether a dependency is working, and the operator's sentence if it is not."""

    ok: bool
    diagnosis: str = ""


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
