# api/services/admin_service.py
import httpx
from api.config import get_settings
from api.auth import hash_password
from api.database import (
    get_system_connection,
    insert_organisation, fetch_all_organisations, fetch_organisation,
    update_organisation, delete_organisation,
    insert_org_membership, fetch_org_members, update_org_membership_role,
    delete_org_membership,
    insert_project_registry, fetch_all_registry, fetch_org_projects,
    delete_project_registry, fetch_project_registry,
    insert_project_membership, delete_project_membership,
    fetch_user_project_memberships,
    insert_user, fetch_all_users, fetch_users_by_org,
    fetch_user_by_id, update_user, delete_user, fetch_user,
)


async def _send_welcome_email(email: str, username: str, password: str) -> None:
    """Send one-time welcome email with credentials via Resend. Silently skips if no API key."""
    settings = get_settings()
    if not settings.resend_api_key or not email:
        return
    login_url = f"{settings.public_url}/dashboard/login"
    body = (
        f"Hello,\n\n"
        f"Your TaskReimagination.ai account has been created.\n\n"
        f"Username: {username}\n"
        f"Temporary password: {password}\n"
        f"Login: {login_url}\n\n"
        f"Please change your password after first login.\n\n"
        f"TaskReimagination.ai"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                "https://api.resend.com/emails",
                json={
                    "from": settings.from_email,
                    "to": [email],
                    "subject": "Your TaskReimagination.ai account has been created",
                    "text": body,
                },
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            )
    except Exception:
        pass  # Email failure must never block user creation


# ── Organisation services ─────────────────────────────────────────────────────

async def svc_list_orgs() -> list[dict]:
    async with get_system_connection() as conn:
        return await fetch_all_organisations(conn)


async def svc_create_org(slug: str, name: str) -> dict:
    async with get_system_connection() as conn:
        org_id = await insert_organisation(conn, slug=slug, name=name)
        return await fetch_organisation(conn, org_id=org_id)


async def svc_get_org(org_id: int) -> dict | None:
    async with get_system_connection() as conn:
        return await fetch_organisation(conn, org_id=org_id)


async def svc_update_org(org_id: int, name: str) -> dict | None:
    async with get_system_connection() as conn:
        org = await fetch_organisation(conn, org_id=org_id)
        if not org:
            return None
        await update_organisation(conn, org_id=org_id, name=name)
        return await fetch_organisation(conn, org_id=org_id)


async def svc_delete_org(org_id: int) -> bool:
    async with get_system_connection() as conn:
        org = await fetch_organisation(conn, org_id=org_id)
        if not org:
            return False
        await delete_organisation(conn, org_id=org_id)
        return True


# ── Org membership services ───────────────────────────────────────────────────

async def svc_list_org_members(org_id: int) -> list[dict]:
    async with get_system_connection() as conn:
        return await fetch_org_members(conn, org_id=org_id)


async def svc_add_org_member(org_id: int, user_id: int, role: str) -> bool:
    async with get_system_connection() as conn:
        return await insert_org_membership(conn, user_id=user_id, org_id=org_id, role=role)


async def svc_update_org_member_role(org_id: int, user_id: int, role: str) -> None:
    async with get_system_connection() as conn:
        await update_org_membership_role(conn, user_id=user_id, org_id=org_id, role=role)


async def svc_remove_org_member(org_id: int, user_id: int) -> None:
    async with get_system_connection() as conn:
        await delete_org_membership(conn, user_id=user_id, org_id=org_id)


# ── Project registry services ─────────────────────────────────────────────────

async def svc_list_registry(payload: dict) -> list[dict]:
    async with get_system_connection() as conn:
        if payload.get("role") == "sysadmin":
            return await fetch_all_registry(conn)
        org_id = payload.get("org_id")
        if org_id:
            return await fetch_org_projects(conn, org_id=org_id)
        return []


async def svc_register_project(slug: str, org_id: int, display_name: str) -> None:
    async with get_system_connection() as conn:
        await insert_project_registry(conn, slug=slug, org_id=org_id, display_name=display_name)


async def svc_unregister_project(slug: str) -> bool:
    async with get_system_connection() as conn:
        row = await fetch_project_registry(conn, slug=slug)
        if not row:
            return False
        await delete_project_registry(conn, slug=slug)
        return True


# ── User services ─────────────────────────────────────────────────────────────

async def svc_list_users(payload: dict) -> list[dict]:
    async with get_system_connection() as conn:
        if payload.get("role") == "sysadmin":
            users = await fetch_all_users(conn)
        else:
            org_id = payload.get("org_id")
            users = await fetch_users_by_org(conn, org_id=org_id) if org_id else []
        # Strip hashed_pw from response
        return [{k: v for k, v in u.items() if k != "hashed_pw"} for u in users]


async def svc_create_user(
    username: str,
    email: str,
    password: str,
    role: str,
    org_id: int | None,
    calling_payload: dict,
) -> dict | None:
    """Create user. Returns user dict (without hashed_pw) or None if username taken."""
    # org_admin can only create org_admin-or-below users within their own org
    if calling_payload.get("role") == "org_admin":
        if role == "sysadmin":
            return None  # org_admin cannot create sysadmins
        org_id = calling_payload.get("org_id")

    hashed = hash_password(password)
    async with get_system_connection() as conn:
        ok = await insert_user(
            conn, username=username, email=email, role=role,
            hashed_pw=hashed, project_slug=None,
        )
        if not ok:
            return None
        user = await fetch_user(conn, username=username)
        if user and org_id:
            await insert_org_membership(
                conn, user_id=user["id"], org_id=org_id,
                role="org_admin" if role == "org_admin" else "member",
            )

    await _send_welcome_email(email, username, password)
    return {k: v for k, v in user.items() if k != "hashed_pw"}


async def svc_update_user(
    user_id: int, email: str, role: str, password: str | None
) -> dict | None:
    async with get_system_connection() as conn:
        user = await fetch_user_by_id(conn, user_id=user_id)
        if not user:
            return None
        hashed = hash_password(password) if password else None
        await update_user(conn, user_id=user_id, email=email, role=role, hashed_pw=hashed)
        updated = await fetch_user_by_id(conn, user_id=user_id)
        return {k: v for k, v in updated.items() if k != "hashed_pw"}


async def svc_delete_user(user_id: int) -> bool:
    async with get_system_connection() as conn:
        user = await fetch_user_by_id(conn, user_id=user_id)
        if not user:
            return False
        await delete_user(conn, user_id=user_id)
        return True


# ── Project membership services ───────────────────────────────────────────────

async def svc_list_user_projects(user_id: int) -> list[dict]:
    async with get_system_connection() as conn:
        return await fetch_user_project_memberships(conn, user_id=user_id)


async def svc_grant_project_access(user_id: int, project_slug: str) -> bool:
    async with get_system_connection() as conn:
        return await insert_project_membership(conn, user_id=user_id, project_slug=project_slug)


async def svc_revoke_project_access(user_id: int, project_slug: str) -> None:
    async with get_system_connection() as conn:
        await delete_project_membership(conn, user_id=user_id, project_slug=project_slug)
