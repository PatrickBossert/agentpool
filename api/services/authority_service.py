"""What the calling account may do on one project.

Read, not inferred. The walk is JWT -> users row -> membership for this slug ->
stakeholder row -> flags, so nothing depends on two tables happening to hold the same
email text. The previous implementation matched on exactly that, and could not work at
all: the users table was empty, so an `if role == "sysadmin": return True` was carrying
every call - granting content authority to whoever could administer accounts.

sys_admin implies project_admin on every project and nothing else. Without it a newly
created project has no stakeholders and no way to add one. The line that matters is
administration versus content, not global versus per-project.
"""
from fastapi import HTTPException

from api.database import get_db_path, get_system_connection, get_connection, fetch_project, fetch_user

_FLAG_ROLES = (
    ("is_project_admin", "project_admin"),
    ("is_governor", "governor"),
    ("is_approver", "approver"),
    ("is_reviewer", "reviewer"),
    ("is_participant", "participant"),
)


async def caller_roles(slug: str, payload: dict) -> set[str]:
    """Every role this caller holds on this project. Empty when they hold none."""
    username = (payload or {}).get("sub", "")
    if not username:
        return set()

    async with get_system_connection() as sys_conn:
        user = await fetch_user(sys_conn, username=username)
        if not user:
            return set()
        roles: set[str] = set()
        if user.get("is_sys_admin"):
            roles |= {"sys_admin", "project_admin"}
        cur = await sys_conn.execute(
            "SELECT stakeholder_id FROM project_memberships WHERE user_id=? AND project_slug=?",
            (user["id"], slug),
        )
        row = await cur.fetchone()

    stakeholder_id = row[0] if row else None
    if stakeholder_id is None:
        return roles

    # get_connection(slug) creates the project's database - mkdir, connect, init_db, and
    # the full migration block - on a slug that has none. Every gated endpoint calls this
    # function now, so an authority check must not have that side effect: a caller probing
    # slugs would otherwise materialise a database file per guess. A project that has never
    # been created has no stakeholders either way, so the answer is the same roles gathered
    # so far, just without the database write.
    if not get_db_path(slug).exists():
        return roles

    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return roles
        cur = await conn.execute(
            "SELECT * FROM stakeholders WHERE id=? AND project_id=?",
            (stakeholder_id, project["id"]),
        )
        person = await cur.fetchone()

    if person is not None:
        roles |= {role for flag, role in _FLAG_ROLES if person[flag]}
    return roles


# ── The two gates every content write is held to ──────────────────────────────
#
# `check_project_access` answers a different question from these: it asks whether the
# caller belongs to the engagement at all, and membership *is* read access by design. It
# has no role test, so before this branch its "reviewer" arm was the whole of the
# authority on several write doors - safe only because `users` held no rows and the
# principal class "authenticated non-admin with a project membership" was empty. The
# invite loop populates that class, so the doors need the role test the walk was built to
# provide.
#
# Two gates, not one per door, so a reviewer looking at any write door can tell which of
# them it is behind without reading its body:
#
#   contribute - leaving feedback on somebody else's work. A review, a change request, a
#                disposition on a validation warning. Nothing here alters what the project
#                currently says; it records what somebody thinks of it.
#   approve    - changing or discarding what the project currently says. A revert, a save
#                of the canonical value chain, deleting a review someone else recorded.
#
# The rule lives here rather than inline in each router, because a condition copied into
# several call sites is a condition that has already started to diverge - see the
# register_scripts_sync / scripts_awaiting_regeneration entry in CLAUDE.md. Routers
# translate the refusal into a 403; they do not decide it.
#
# `commit_service.caller_may_commit` and `caller_may_submit` are the same two rules under
# older names, and they now delegate here rather than restating the role sets - committing
# is approving, submitting is contributing. They were left restating them once, on the
# grounds that the branch's verified chain ran through them; it runs through `caller_roles`'
# walk, not through those two role sets, so the copies were only copies. The rule is stated
# here and nowhere else.
CONTRIBUTOR_ROLES = frozenset({"reviewer", "approver"})
APPROVER_ROLES = frozenset({"approver"})


async def caller_may_contribute(slug: str, payload: dict) -> bool:
    """Whether this caller may record feedback against this project's work."""
    return bool(await caller_roles(slug, payload) & CONTRIBUTOR_ROLES)


async def caller_may_approve(slug: str, payload: dict) -> bool:
    """Whether this caller may change or discard this project's canonical state."""
    return bool(await caller_roles(slug, payload) & APPROVER_ROLES)


# ── The administration axis, per project ──────────────────────────────────────
#
# The two gates above are the *content* axis. This is the other one, and until sp44 it had
# no per-project half at all: every project-configuration door asked
# `require_org_admin_or_above`, which reads the JWT's login role and knows nothing of slugs.
# That was not the intent - `project_admin` is the design's name for "configures this
# project and its people" - it was the only reachable rule while the role was ungrantable.
#
# The disjunction lives here, once. Sixteen doors ask it, and a condition copied into
# sixteen call sites is a condition that has already started to diverge - see the
# register_scripts_sync / scripts_awaiting_regeneration entry in CLAUDE.md, where two copies
# of one WHERE clause did exactly that.
#
# Naming, deliberately: `_assert_may_administer` (admin_service.py) decides who may
# administer an *account*, and `check_org_access` (api/auth.py) who may administer an
# *organisation*. Neither is this, and neither is widened by it. The `_project` suffix is
# load-bearing.
PROJECT_ADMINISTRATION_REQUIRED = (
    "Project administration required - org admin or above, or project_admin on this project"
)


async def caller_may_administer_project(slug: str, payload: dict) -> bool:
    """Whether this caller may configure this engagement - its people, schedule and settings.

    Either arm suffices:

      platform tier - `sysadmin` or `org_admin` on the login. The consultant running the
                      engagement, unchanged from sp38. `check_project_access` is what scopes
                      an org_admin to their own organisation's slugs, so this must always be
                      called *after* the floor, never instead of it.
      project_admin - the per-project half, read by the walk from the caller's stakeholder
                      row. `is_sys_admin` implies it on every project, which is why a
                      sysadmin needs no third arm here.

    Not `caller_roles(...) & {"project_admin"}` alone: an org_admin normally holds no
    stakeholder row on the projects they administer, so the walk answers an empty set for
    exactly the caller sp38's gates were written for.
    """
    if payload.get("role") in ("sysadmin", "org_admin"):
        return True
    return "project_admin" in await caller_roles(slug, payload)


async def require_project_administration(slug: str, payload: dict) -> None:
    """`caller_may_administer_project` as a refusal, for the sixteen doors that need it.

    The 403 is raised here rather than in each router - the rule and the sentence it is
    refused with are one thing, and sixteen restatements of the sentence would drift the way
    the roles they replace did. `check_project_access` in api/auth.py already sets this
    precedent for the membership floor.
    """
    if not await caller_may_administer_project(slug, payload):
        raise HTTPException(status_code=403, detail=PROJECT_ADMINISTRATION_REQUIRED)


def require_writable_tier(tier: str, payload: dict) -> None:
    """`assert_may_write_tier` as a status code, for the two upload doors.

    The rule itself lives in `api/services/knowledge_tiers.py` - this is only the translation,
    stated once so the two doors cannot answer the same refusal differently. Same shape as
    `require_project_administration` above, and for the same reason.

    422 for a tier that does not exist, 403 for one that does and is not the caller's. Folding
    them together would tell a reviewer who asked for the sector store that they had made a
    typo, and tell somebody who did make a typo that they lacked authority.
    """
    from api.services.knowledge_tiers import TierWriteRefused, assert_may_write_tier

    try:
        assert_may_write_tier(tier, payload)
    except TierWriteRefused as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


async def caller_may_grant_project_roles(slug: str, payload: dict) -> bool:
    """Whether this caller may *grant* `is_project_admin` or `is_governor` on this project.

    Strictly narrower than `caller_may_administer_project`: `project_admin` and nothing else,
    so an org_admin who administers the engagement still cannot mint one. A role that confers
    the right to hand itself out has to have exactly one route in, or the recursion has two
    base cases and only one of them is documented.

    The sysadmin arm is that same base case, not a second one. `is_sys_admin` implies
    `project_admin` in `caller_roles`, which is what lets a fresh project - no stakeholders,
    so nobody the walk can reach - be bootstrapped at all. But the *built-in* administrator
    has no `users` row for the walk to read it off: `POST /auth/login` matches
    ADMIN_USERNAME from the environment before it ever looks at the table, and mints a
    role="sysadmin" token for a login the system database has never heard of. Reading the
    implication only off `users.is_sys_admin` therefore refuses the one caller it exists to
    serve, on every deployment where the operator is the env-var admin - which is all of
    them, since ADMIN_USERNAME is required and has no default.

    Read off the token rather than the row *here only*, and deliberately not inside
    `caller_roles`: the walk stays a database read, so a stale or forged `role="sysadmin"`
    claim still buys nothing from it (`tests/test_admin.py::
    test_org_admin_cannot_promote_anyone_to_sysadmin` asserts exactly that, on a hand-built
    payload). This is no weaker than the door it stands beside - every administration gate
    on this codebase already trusts the same claim through `require_org_admin_or_above` -
    and it confers no content authority whatever.
    """
    if payload.get("role") == "sysadmin":
        return True
    return "project_admin" in await caller_roles(slug, payload)
