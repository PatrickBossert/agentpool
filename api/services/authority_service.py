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
from api.database import get_system_connection, get_connection, fetch_project, fetch_user

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
