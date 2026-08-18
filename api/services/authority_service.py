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


# ── Write authority follows the tier ──────────────────────────────────────────
#
# `knowledge_tiers.writable_tiers` answers how wide a caller may write **from their login
# role alone** - sector is sysadmin, organisation is org_admin or above, project is narrower
# still. It is pure and it knows no slug, which is what lets GET /my-permissions and the
# upload doors share one statement of it, and it is also exactly what it cannot answer:
# *which* organisation's store an org_admin may write into.
#
# That distinction is the whole of the risk. `org_{org_slug}` is shared by every project of
# one organisation, and on a consultancy deployment the organisations are different clients.
# "May write the organisation tier" in the abstract is not a permission anybody should hold;
# "may write their own organisation's store" is.
#
# So the rule is completed here, where a slug is available:
#
#   sector       sysadmin. A deployment-wide store takes the deployment-wide role, and there
#                is no second question - it is one store, not one per organisation.
#   organisation org_admin or above, **for the organisation this project belongs to**. The
#                destination is read from `project_registry`; a project with no row belongs
#                to no organisation and has no organisation tier at all.
#   project      authority over this project - administering it, or approving its content.
#                Both are per-project and both are read by the walk above, so neither
#                depends on which door the caller came through.
#
# **Whether the caller can write the row the boundary reads** is the question sp42 and sp38
# were both about, and it is asked of both premises here:
#
#   `project_registry.org_id` - `POST`/`DELETE /auth/projects` are sysadmin-only, and project
#   creation registers through `register_project_if_unregistered`, which cannot move a slug
#   that already has a row. See the report for the one residual case, which is a hole in
#   `POST /projects` rather than in this rule.
#
#   the caller's own `org_id` - minted from `org_memberships` at login and **re-derived on
#   every rolled request** (api/main.py `_current_session_claims`), so it is a live read of a
#   table whose three write doors are all scoped by `check_org_access` to the caller's own
#   organisation. An org_admin cannot add themselves to another organisation, which is the
#   chain sp42 closed.
#
# `check_project_access` refuses an org_admin every slug outside their organisation, so the
# boundary is enforced twice on today's doors. That is deliberate: the floor answers "is this
# your engagement", this answers "is that your store", and they are only the same answer for
# as long as every door remembers the floor.


async def may_write_tier_on_project(slug: str, tier: str, payload: dict) -> bool:
    """Whether this caller may add material at `tier` on this project.

    Raises `ValueError` for a tier that does not exist, or that does not exist *for this
    project* - which is a different thing from a refusal and owes the caller a different
    answer. Returns False for a tier that exists and is not theirs.
    """
    from api.auth import may_access_org
    from api.database import fetch_project_registry
    from api.services.knowledge_tiers import TierWriteRefused, assert_may_write_tier

    # The login-role half first: it settles the vocabulary (raising on a tier that does not
    # exist) and the sector, and it is the only half GET /my-permissions could answer before.
    try:
        assert_may_write_tier(tier, payload)
    except TierWriteRefused:
        return False

    if tier == "sector":
        return True

    if tier == "organisation":
        async with get_system_connection() as conn:
            row = await fetch_project_registry(conn, slug=slug)
        if not row:
            raise ValueError(
                f"'{slug}' has no project_registry row, so it belongs to no organisation "
                f"and has no organisation tier to write into. Register the project against "
                f"an organisation first."
            )
        return may_access_org(row["org_id"], payload)

    # The project tier. `writable_tiers` hands it to every caller, because a login role says
    # nothing about one engagement; the authority for a project write is per-project and is
    # read by the walk. Administration or approval, because both doors' gates are real
    # authority over this project and the tier must not depend on which one was used.
    return await caller_may_administer_project(
        slug, payload
    ) or await caller_may_approve(slug, payload)


async def assert_may_write_tier_on_project(slug: str, tier: str, payload: dict) -> None:
    """`may_write_tier_on_project` as a refusal. The rule, not its status code.

    The sentence names the tier it is refusing once, as `at the <tier> tier`, and the tiers
    it is *not* refusing only as stores - so a test asserting the refusal cannot be satisfied
    by a refusal of some other tier. CLAUDE.md records the shape: a refusal message that
    quotes the key it is refusing turns a substring assertion into a tautology.
    """
    from api.services.knowledge_tiers import TierWriteRefused

    if not await may_write_tier_on_project(slug, tier, payload):
        permitted = await writable_tiers_on_project(slug, payload)
        raise TierWriteRefused(
            f"You may not add material at the {tier} tier of '{slug}'. Material only ever "
            f"moves narrower, so writing it needs authority for the destination: the sector "
            f"store is sysadmin alone and the organisation store is org admin or above for "
            f"that organisation. On this project you may write: "
            f"{', '.join(permitted) or 'nothing'}."
        )


async def writable_tiers_on_project(slug: str, payload: dict) -> tuple[str, ...]:
    """The tiers this caller may write on this project, broadest first.

    What GET /my-permissions answers with, so the upload dialog's tier picker filters on the
    server's answer rather than restating the rule in TypeScript - a second copy of an
    authority rule is what this codebase has spent a fortnight deleting, and the copy the UI
    trusted would be the one that drifted.

    A tier that does not exist for this project is simply absent, exactly like one the caller
    may not write: a control that 403s on submit is worse than one that is not there.
    """
    from api.services.knowledge_tiers import UPLOADABLE_TIERS

    allowed = []
    for tier in UPLOADABLE_TIERS:
        try:
            if await may_write_tier_on_project(slug, tier, payload):
                allowed.append(tier)
        except ValueError:
            continue
    return tuple(allowed)


async def require_writable_tier(slug: str, tier: str, payload: dict) -> None:
    """The tier rule as a status code, for the two upload doors.

    The rule is above and in `api/services/knowledge_tiers.py`; this is only the translation,
    stated once so the two doors cannot answer the same refusal differently. Same shape as
    `require_project_administration`, and for the same reason.

    422 for a tier that does not exist - including one that does not exist *for this project*,
    which is the unregistered-project case - and 403 for one that does and is not the
    caller's. Folding them together would tell a reviewer who asked for the sector store that
    they had made a typo, and tell somebody who did make a typo that they lacked authority.
    """
    from api.services.knowledge_tiers import TierWriteRefused

    try:
        await assert_may_write_tier_on_project(slug, tier, payload)
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
