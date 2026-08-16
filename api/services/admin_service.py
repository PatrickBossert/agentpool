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
    fetch_user_by_id, update_user, delete_user, fetch_user, fetch_user_org,
)
from api.services.invite_service import deliver_reset


class OrganisationInUse(Exception):
    """Deleting this organisation would recreate the defect this branch exists to close.

    `organisations` is the parent of `project_registry` under ON DELETE CASCADE, and
    `check_project_access` resolves an org_admin by reading exactly that table. So a single
    successful 204 here silently unregisters every project the organisation owned - no error,
    no warning, and an org_admin refused on engagements they held a moment earlier, with
    `project_memberships` looking perfectly correct throughout. That is precisely the state
    this branch found the live deployment in, reachable again in one call.

    Two conditions, because they catch different failures and neither implies the other:

      home     - the organisation `home_org_slug` names. Project *creation* resolves against
                 it, so deleting it breaks new projects as well as existing access. It can be
                 entirely empty of projects, so a projects-only rule would wave it through.
      in use   - any organisation that still owns registered projects. Catches the non-home
                 organisation the first condition says nothing about.

    Raised rather than returned: `svc_delete_org` already returns False for "no such
    organisation", and answering a refusal with 404 would tell the operator the opposite of
    what happened.
    """


class ForbiddenRoleChange(Exception):
    """An org_admin tried to hand out sysadmin.

    svc_create_user answers this case by returning None, which the router turns into a 409 -
    but None already means "no such user" on the update path, and answering a refused
    promotion with 404 would both mislead the caller and leave a test unable to tell the
    refusal from a user that was simply never created. Same rule, same 409, told apart from
    "not found" by being raised rather than returned.
    """


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
    """Delete an organisation that nothing depends on. See OrganisationInUse for why not."""
    async with get_system_connection() as conn:
        org = await fetch_organisation(conn, org_id=org_id)
        if not org:
            return False
        home_slug = get_settings().home_org_slug
        if org["slug"] == home_slug:
            raise OrganisationInUse(
                f"'{org['slug']}' is the home organisation (HOME_ORG_SLUG={home_slug})."
                " Every project created without an organisation of its own is registered"
                " against it, so deleting it would break project creation as well as"
                " unregistering what it owns. Point HOME_ORG_SLUG at another organisation"
                " first if this one is really to go."
            )
        owned = await fetch_org_projects(conn, org_id=org_id)
        if owned:
            names = ", ".join(sorted(p["slug"] for p in owned))
            raise OrganisationInUse(
                f"'{org['slug']}' still owns {len(owned)} registered project(s): {names}."
                " Deleting it would cascade through project_registry and silently remove"
                " every org_admin's access to them. Reassign them through POST /auth/projects"
                " or unregister them through DELETE /auth/projects/{slug} first."
            )
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
    user_id: int, email: str, role: str, password: str | None, calling_payload: dict
) -> dict | None:
    """Edit a login. Returns the user dict (without hashed_pw), or None if there is no such
    user; raises ForbiddenRoleChange if the caller may not grant the role asked for, and
    AccountOutOfScope if they may not act on this account at all.

    The two are different questions and only the first was ever asked here. The guard below
    tests the role being *granted*; `_assert_may_administer` tests the account being
    *edited*. Without the second, an org_admin could PATCH an existing sysadmin with
    `role="org_admin"` and a password of their own choosing - the platform administrator
    demoted and their login taken in one request, with the role guard never firing because
    the role being granted was not sysadmin. `password` is what makes it a takeover rather
    than vandalism, and this endpoint has always accepted one.

    The same guard svc_create_user carries, on the door that had none. PATCH
    /auth/users/{id} is require_org_admin_or_above, so without it an org_admin who could not
    *create* a sysadmin could create a reviewer and then promote it - or promote themselves.
    That has been an escalation for as long as login has minted the JWT role from
    user["role"]; what makes it this branch's business is that is_sys_admin now travels with
    the role, so caller_roles reads the promotion back as project_admin on every project in
    the system. The walk is where authority is read, so the guard belongs on every path that
    can change what the walk will say.
    """
    if calling_payload.get("role") == "org_admin" and role == "sysadmin":
        raise ForbiddenRoleChange("org_admin cannot grant sysadmin")

    async with get_system_connection() as conn:
        user = await fetch_user_by_id(conn, user_id=user_id)
        if not user:
            return None
        await _assert_may_administer(conn, calling_payload=calling_payload, target=user)
        hashed = hash_password(password) if password else None
        await update_user(conn, user_id=user_id, email=email, role=role, hashed_pw=hashed)
        updated = await fetch_user_by_id(conn, user_id=user_id)
        return {k: v for k, v in updated.items() if k != "hashed_pw"}


class AccountOutOfScope(Exception):
    """This caller may not act on this account, whatever they were asking to do to it.

    Raised rather than returned for the same reason ForbiddenRoleChange is: None already
    means "no such user" on these paths, and answering a refusal with 404 would tell the
    operator the opposite of what happened.
    """


# One sentence for both conditions below, deliberately. Told apart, the refusals are an
# oracle: "that is a sysadmin" and "that account belongs to another organisation" are two
# facts about an account an org_admin is not entitled to read, and enumerating ids would
# hand them both.
_OUT_OF_SCOPE = "that account is not yours to administer"


async def _assert_may_administer(conn, *, calling_payload: dict, target: dict) -> None:
    """May this caller act on this target account? The one place the question is answered.

    Every door that administers an account asks this and none of them re-states it -
    `svc_issue_reset_link`, `svc_update_user`, and `svc_delete_user` all call this. That is
    not tidiness: this project has already watched two copies of a condition diverge
    (`register_scripts_sync` against `scripts_awaiting_regeneration`, still divergent), and a
    condition that is copied per door is a condition that will be right on some doors and
    wrong on others. It was already wrong on two of the three - see below.

    Two refusals, and neither is expressible as a role tier, which is why
    `require_org_admin_or_above` on the routers cannot stand in for them:

      sysadmin target - an org_admin may not act on a sysadmin's account at all.
        `svc_create_user` and `svc_update_user` both refused to *grant* sysadmin already,
        which reads like the same rule and is not: the older guard tested the role being
        granted, never the account being edited, so `PATCH /auth/users/{id}` with
        `role="org_admin"` and a password of the caller's choosing demoted the platform
        administrator and took their login in a single request, without the guard firing.
        `svc_delete_user` asked nothing at all.

      other organisation - an org_admin may only act on accounts in their own organisation.
        `svc_create_user` forces `org_id` to the caller's own and `svc_list_users` scopes
        what they can see; `svc_update_user` and `svc_delete_user` had no equivalent, so the
        id in the URL walked round a filter applied everywhere else.

    A sysadmin returns early - administering across organisations is a sysadmin capability
    throughout this file, and a guard that refused everybody would close the finding by
    breaking the only legitimate route to it.

    An org_admin with no `org_id` in their session is refused rather than waved through: a
    missing claim is not a licence, and `/auth/login` embeds one for every real org_admin.
    """
    if calling_payload.get("role") != "org_admin":
        return
    if target["role"] == "sysadmin":
        raise AccountOutOfScope(_OUT_OF_SCOPE)
    caller_org = calling_payload.get("org_id")
    org_row = await fetch_user_org(conn, user_id=target["id"])
    if caller_org is None or org_row is None or org_row["org_id"] != caller_org:
        raise AccountOutOfScope(_OUT_OF_SCOPE)


async def svc_issue_reset_link(user_id: int, calling_payload: dict) -> dict | None:
    """Mint a password-reset link for a named account and hand the raw token back.

    Returns None when there is no such user; raises AccountOutOfScope when the caller may not
    reset this one.

    Returning the token is the same decision `POST /{slug}/stakeholders/{id}/resend-invite`
    already made, for the same reason: there is no wired outbound-email path (FROM_EMAIL
    names a domain that is not verified in Resend), so the administrator who asked for the
    link is the one who delivers it. That is acceptable here because the caller is already
    org_admin or above - a tier that can set this account's password outright through
    `PATCH /auth/users/{id}` - so the link grants them nothing they could not already do,
    and it is strictly the *better* of the two, since the account owner chooses the new
    password rather than being handed one the administrator knows.

    Who may do it is `_assert_may_administer`'s question, not this function's - the same
    question `svc_update_user` and `svc_delete_user` ask, answered once.

    `deliver_reset` is passed `users.username`, not `users.email`: it looks its account up
    as a username (see invite_service.issue_reset), and while every invite-created login has
    the two equal, an administrator-created one need not - passing the email there would
    mint a token no redemption could resolve, and `issue_reset` would roll it back and
    answer None, so the operator would see "no such account" for an account plainly in front
    of them.
    """
    async with get_system_connection() as conn:
        user = await fetch_user_by_id(conn, user_id=user_id)
        if not user:
            return None
        await _assert_may_administer(conn, calling_payload=calling_payload, target=user)

    raw = await deliver_reset(email=user["username"])
    if raw is None:
        return None
    return {"reset_token": raw, "username": user["username"], "email": user["email"]}


async def svc_delete_user(user_id: int, calling_payload: dict) -> bool:
    """Delete a login. False if there is no such user; raises AccountOutOfScope if the caller
    may not act on it.

    `calling_payload` is new, and its absence was the whole defect: this door asked nothing
    about the target at all, so an org_admin could delete a sysadmin, or anybody in any other
    organisation, by id - the same gap `svc_update_user` had, reached with one fewer field to
    fill in. The router took its dependency in the decorator, which is exactly how a door
    ends up unable to ask the question: there was no payload in the handler to pass on.
    """
    async with get_system_connection() as conn:
        user = await fetch_user_by_id(conn, user_id=user_id)
        if not user:
            return False
        await _assert_may_administer(conn, calling_payload=calling_payload, target=user)
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
