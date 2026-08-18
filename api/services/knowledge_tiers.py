# api/services/knowledge_tiers.py
"""The four knowledge tiers, and the one place a Chroma collection name is built.

Knowledge in this deployment sits at one of three widths, and the difference should be a
declaration rather than an accident:

| Tier | Collection | Holds |
|---|---|---|
| `sector` | `sector_{sector}` | industry trends, regulatory context, benchmarks - shared by every engagement in that sector |
| `organisation` | `org_{org_slug}` | annual reports, strategy, group policy - shared by every project of one organisation |
| `project` | `{slug}_docs` | this project's own uploaded documents |
| `interviews` | `{slug}_interviews` | this project's interview answers |

Containment, not override: an agent may read all four, and nothing broader is hidden by
anything narrower. A query names **one** tier and gets that tier - there is no cross-tier
merging or ranking here, deliberately.

**Why this module exists at all: the fallback.** `ChromaQueryTool` resolved its collection
argument with

    }.get(collection, f"sector_{self.sector}")

so the store shared across every engagement in a sector was the answer to any name the dict
did not hold - a typo, a renamed tier, an agent inventing a plausible word. That is one
client's material arriving in another client's search results, silently, and it read in the
graph as a deliberate sector read. Six agents hold the tool; three are declared to read the
sector store.

So the vocabulary is closed and **an unrecognised tier raises**. Refusal is the whole point:
falling back to anything, and to the widest store in particular, is the defect.

The same reasoning applies one level down, to a tier whose key is missing or blank.
`sector_` and `_docs` are perfectly valid Chroma collection names, and each would be a store
silently shared by every project whose key happened to be empty. They raise too.
"""
from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Literal

from api.config import get_settings

# Broadest to narrowest. The order is the containment hierarchy and is worth preserving:
# anything presenting the tiers to a person should present them this way round.
KNOWLEDGE_TIERS: tuple[str, ...] = ("sector", "organisation", "project", "interviews")

Tier = Literal["sector", "organisation", "project", "interviews"]

# The tiers whose store holds more than this engagement's material. Declared rather than
# derived from the collection template, because the two are different claims and the privacy
# page asserts them against each other: `is_shared_beyond_one_project` reads the *name* and
# answers "this template carries no slug", while this reads the *tier* and answers "this store
# is meant to be shared". A tier renamed into a slug-less template, or a template that gained a
# slug without the tier changing, is a disagreement worth failing on rather than a rename.
SHARED_TIERS: tuple[str, ...] = ("sector", "organisation")

# How wide each tier's store is, in the sentence an auditor reads on the privacy page. Prose,
# because nothing derives it, and it is the *reason* rather than the fact: the page could
# already say `sector_{sector}` is "not scoped to this project" and had no vocabulary for why
# it is not, nor any way to tell that store apart from `org_{org_slug}`, which is shared with a
# quite different set of people.
#
# Written from the reader's side of the boundary - "other clients'", not "other engagements" -
# because a client reading this page wants to know who else is in the store, and the honest
# answer for the sector tier on the consultancy's own deployment is: their competitors.
TIER_SCOPE: dict[str, str] = {
    "sector": (
        "shared by every engagement in this sector, on this deployment - including other "
        "clients' engagements"
    ),
    "organisation": (
        "shared by every project of this organisation, and by no project of any other "
        "organisation"
    ),
    "project": "this project's own uploaded documents, and no other project's",
    "interviews": "this project's own interview answers, and no other project's",
}


def collection_for(
    tier: str,
    *,
    slug: str,
    sector: str | None = None,
    org_slug: str | None = None,
) -> str:
    """The Chroma collection holding `tier`'s material for this project.

    Raises `ValueError` for anything that is not one of `KNOWLEDGE_TIERS`, and for a tier
    whose key is missing or blank. Never falls back to another tier.

    `org_slug` comes from `project_registry.org_id` (see `org_slug_for_project`). A project
    with no registry row has **no organisation tier** - not an empty one, and certainly not
    the sector store - so the organisation tier is refused for it. That is the same answer
    `check_project_access` already gives such a project on its org branch, and it is a live
    state rather than a hypothetical one: before sp39 every project lacked a registry row.
    """
    if tier not in KNOWLEDGE_TIERS:
        raise ValueError(
            f"Unknown knowledge tier {tier!r}. Valid tiers are: "
            f"{', '.join(KNOWLEDGE_TIERS)}."
        )

    if tier == "sector":
        if not (sector or "").strip():
            raise ValueError(
                "The sector tier needs a sector. This project names none, and 'sector_' "
                "would be a store shared by every project that names none."
            )
        return f"sector_{sector}"

    if tier == "organisation":
        if not (org_slug or "").strip():
            raise ValueError(
                "The organisation tier needs an organisation. This project has no "
                "project_registry row, so it belongs to no organisation and has no "
                "organisation tier to read."
            )
        return f"org_{org_slug}"

    if not (slug or "").strip():
        raise ValueError(f"The {tier} tier needs a project slug.")

    # `_docs`, not `_documents`: the design document writes `{slug}_documents`, but every
    # collection this deployment has ever written is `{slug}_docs` - the ingest service, the
    # document router's delete, and DocumentIngestionTool all build it that way. Renaming it
    # here would orphan every ingested document on the live deployment, so the code wins.
    return f"{slug}_docs" if tier == "project" else f"{slug}_interviews"


# ── Writing: material only ever moves narrower ───────────────────────────────────────────
#
# Reading is containment - an agent may read all four tiers and nothing broader is hidden by
# anything narrower. Writing is the opposite shape, and deliberately so: a project's documents
# never land in its organisation's store, and an organisation's never land in its sector's.
# Without that rule one division's investment proposals become another division's search
# results, and nobody would think to look for the reason.
#
# So promotion to a broader tier is a **deliberate act with authority for the destination**,
# never a side effect of ingestion. There is no promotion door on this branch (see the task
# report): a document reaches a broader store only by being uploaded there, by somebody who
# may write there, and the tier is declared at the door rather than inferred afterwards.

# The tiers a document may be uploaded at. `interviews` is deliberately absent: that store is
# written by the interview pipeline out of what somebody actually said, and a document filed
# into it would be retrieved with an answer's provenance.
UPLOADABLE_TIERS: tuple[str, ...] = ("sector", "organisation", "project")

# The narrowest, because the safe case must not be the one that requires thought. A default of
# `organisation` would make every unconsidered upload a shared one.
DEFAULT_UPLOAD_TIER = "project"


class TierWriteRefused(Exception):
    """The caller may not write the tier they declared.

    Distinct from `ValueError`, which is what an unknown tier raises: one is a caller who
    asked for something that does not exist, the other a caller who asked for something that
    does exist and is not theirs. The routers owe them different status codes.
    """


def writable_tiers(payload: dict | None) -> tuple[str, ...]:
    """The tiers this caller may write material into, broadest first.

    Decided by the caller's authority and by nothing else - emphatically not by which door
    they came through. The two upload doors are gated differently today (the chat door on the
    `approver` content role, the documents door on `require_org_admin_or_above`), which is a
    known asymmetry this branch does not reconcile; what it must not do is let that asymmetry
    decide how wide a store a caller can reach.

    `sector` is sysadmin alone. On a consultancy deployment a sector store spans *different
    clients*, which is either the product's value or its worst leak depending entirely on
    what goes into it, so it takes the only role that is scoped to the whole deployment.

    `organisation` is org_admin or above. An org_admin administers exactly one organisation
    and `check_project_access` already refuses them every slug outside it, so the destination
    they can reach is their own organisation's store and no other.

    `project` is everybody who got through the door at all. The tier adds nothing there - the
    door's own gate is the authority for a project write, and always has been.
    """
    role = (payload or {}).get("role")
    if role == "sysadmin":
        return ("sector", "organisation", "project")
    if role == "org_admin":
        return ("organisation", "project")
    return ("project",)


def assert_may_write_tier(tier: str, payload: dict | None) -> None:
    """Raise unless this caller may write `tier`. The rule, not its status code.

    Lives here rather than in either router because a condition copied into two call sites is
    a condition that has already started to diverge - see the register_scripts_sync /
    scripts_awaiting_regeneration entry in CLAUDE.md, where two copies of one WHERE clause did
    exactly that. Routers translate the refusal into a status code; they do not own the rule.
    """
    if tier not in UPLOADABLE_TIERS:
        raise ValueError(
            f"Unknown knowledge tier {tier!r}. A document may be uploaded at: "
            f"{', '.join(UPLOADABLE_TIERS)}."
        )
    if tier not in writable_tiers(payload):
        raise TierWriteRefused(
            f"You may not add material at the {tier} tier. Material only ever moves narrower, "
            f"so writing it needs authority for the destination: the sector store is sysadmin "
            f"alone and the organisation store is org admin or above. You may write: "
            f"{', '.join(writable_tiers(payload))}."
        )


def org_slug_for_project(slug: str) -> str | None:
    """The slug of the organisation this project belongs to, or None if it belongs to none.

    Synchronous, and opening its own connection, because the callers are: `ChromaQueryTool`
    runs in CrewAI's thread pool rather than the event loop. This is the shape
    `chroma_client.project_llm_mode` already uses for the same reason.

    None on any failure, including a missing system database. The caller's response to None
    is to refuse the organisation tier, so a failed read costs a refusal rather than a wrong
    store - which is the direction to fail in when the alternative is reading somebody
    else's material.
    """
    path = Path(get_settings().database_dir) / "system.db"
    if not path.exists():
        return None
    try:
        with contextlib.closing(sqlite3.connect(path)) as conn:
            row = conn.execute(
                "SELECT o.slug FROM project_registry p "
                "JOIN organisations o ON o.id = p.org_id WHERE p.slug=?",
                (slug,),
            ).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None
