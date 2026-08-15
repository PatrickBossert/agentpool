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
# older names, reached through the same walk. They are left as they are - the branch's
# verified Critical chain runs through them - so treat this comment as the place the rule
# is stated and those two as call sites of it.
CONTRIBUTOR_ROLES = frozenset({"reviewer", "approver"})
APPROVER_ROLES = frozenset({"approver"})


async def caller_may_contribute(slug: str, payload: dict) -> bool:
    """Whether this caller may record feedback against this project's work."""
    return bool(await caller_roles(slug, payload) & CONTRIBUTOR_ROLES)


async def caller_may_approve(slug: str, payload: dict) -> bool:
    """Whether this caller may change or discard this project's canonical state."""
    return bool(await caller_roles(slug, payload) & APPROVER_ROLES)
