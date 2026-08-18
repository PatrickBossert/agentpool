# api/services/admin_service.py
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
    fetch_user_project_memberships, fetch_project_memberships,
    insert_user, fetch_all_users, fetch_users_by_org,
    fetch_user_by_id, update_user, delete_user, fetch_user, fetch_user_org,
    fetch_user_org_ids,
)
from api.services.invite_service import deliver_reset
from api.services.outbound_mail import send_platform_mail
from api.services.user_identity import person_block, project_identities


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
    """Send one-time welcome email with credentials. Silently skips if no API key.

    Platform correspondence, not a project correspondent's - so it goes through
    `send_platform_mail` rather than `send_project_mail`, and no project's `dev_mode`
    is consulted. This message announces a *login*, not an engagement: it carries no
    slug, the account may belong to no project yet, and it is issued by the platform
    rather than composed by an agent. Forcing it through a project-scoped seam would
    mean inventing a project to consult, and signing it as a persona would put
    somebody's name on credentials they did not issue.

    The consequence is stated rather than hidden: `dev_mode` does not hold this
    message. A project-scoped hold cannot honestly cover a message with no project.
    The setting that should cover it is a platform-level one, and it does not exist.
    """
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
        await send_platform_mail(
            to=email,
            subject="Your TaskReimagination.ai account has been created",
            body=body,
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
    # Deliberately carries no person block. A name lives on a stakeholder row, which is per
    # *project*, and an organisation is not a project - there is no lens here to read a name
    # through. The place that question is asked and answered is the project-scoped user list.
    async with get_system_connection() as conn:
        return await fetch_org_members(conn, org_id=org_id)


async def svc_add_org_member(
    org_id: int, user_id: int, role: str, calling_payload: dict
) -> bool:
    """Add a login to an organisation. False if it is already a member; raises
    AccountOutOfScope if the caller may not claim this account.

    The router has already confirmed `org_id` is the caller's own organisation
    (`check_org_access`). This is the other half: an org_admin may add an account that no
    organisation holds, and may not add one another organisation already does. Without it,
    scoping the door by its path achieved nothing - the caller would simply add somebody
    else's account to their own organisation, and `_assert_may_administer` would then find a
    membership of theirs on it. Claiming, rather than moving: removing the account's real
    membership is a second door, and it is scoped to that organisation.

    A sysadmin is exempt, as everywhere else here - moving an account between organisations is
    a legitimate act, and theirs to perform.
    """
    async with get_system_connection() as conn:
        if calling_payload.get("role") != "sysadmin":
            held = await fetch_user_org_ids(conn, user_id=user_id)
            if any(held_org != org_id for held_org in held):
                raise AccountOutOfScope(_OUT_OF_SCOPE)
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

async def svc_list_users(payload: dict, *, project_slug: str | None = None) -> list[dict]:
    """The accounts this caller may administer - through the lens of one project, or not.

    **Unscoped** (`project_slug` is None) is exactly the list this endpoint has always
    returned, and it carries **no `person` field at all**. That is deliberate rather than
    lazy: a name lives on a stakeholder row, per project, so without a project there is no
    question a name is the answer to, and the honest thing is to have no column rather than
    an arbitrarily chosen one. It stays the default because it is the only view that can show
    every account - including the built-in administrator, and any login created directly -
    and an administration screen that could not list an account it can delete would be a
    worse defect than the one this change fixes.

    **Scoped** returns the accounts holding a membership on that project, each with the name
    and entity *that project* records for them. The slug is authorised by the router through
    `check_project_access` before it gets here, so no project the caller may not administer
    is ever opened.

    Three properties hold, and each is asserted:

      subset       the scoped list never contains an account the unscoped list would not
                   have. It is built by *filtering* the caller's own answer, not by querying
                   `project_memberships` outwards, so an account the caller cannot see cannot
                   arrive through a membership. This is what keeps the project lens from
                   becoming a way round `fetch_users_by_org`.
      sysadmins    a sysadmin holds no membership on most projects, so a platform
                   administrator selecting a project would otherwise watch their own account
                   vanish. Sysadmin accounts are therefore kept regardless of membership -
                   **only for a sysadmin caller**. `fetch_users_by_org` shows an org_admin a
                   sysadmin only when that sysadmin holds a membership of their organisation,
                   and starting to show them unconditionally would confirm the existence of
                   accounts an org_admin has no way to learn about today.
      no guessing  a membership with a NULL stakeholder_id - the /admin access grant - keeps
                   its row and gets `person: null`. It is access without a person record, not
                   a person whose name we failed to find.
    """
    async with get_system_connection() as conn:
        users = await _scoped_users(conn, payload)
        # Strip hashed_pw from response
        users = [{k: v for k, v in u.items() if k != "hashed_pw"} for u in users]
        if project_slug is None:
            return users
        memberships = await fetch_project_memberships(conn, project_slug=project_slug)

    stakeholder_by_user = {m["user_id"]: m["stakeholder_id"] for m in memberships}
    keep_sysadmins = payload.get("role") == "sysadmin"
    scoped = [
        u for u in users
        if u["id"] in stakeholder_by_user or (keep_sysadmins and u["role"] == "sysadmin")
    ]
    wanted = [
        stakeholder_by_user[u["id"]]
        for u in scoped
        if stakeholder_by_user.get(u["id"]) is not None
    ]
    identities = await project_identities(project_slug, wanted)
    for user in scoped:
        stakeholder_id = stakeholder_by_user.get(user["id"])
        user["person"] = person_block(
            identities.get(stakeholder_id) if stakeholder_id is not None else None
        )
    return scoped


async def _scoped_users(conn, payload: dict) -> list[dict]:
    """The user rows this caller may list at all - the endpoint's long-standing answer,
    unchanged, and the set every project-scoped view is a subset of."""
    if payload.get("role") == "sysadmin":
        return await fetch_all_users(conn)
    org_id = payload.get("org_id")
    return await fetch_users_by_org(conn, org_id=org_id) if org_id else []


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

      other organisation - an org_admin may only act on accounts whose *only* organisation is
        their own. `svc_create_user` forces `org_id` to the caller's own and `svc_list_users`
        scopes what they can see; `svc_update_user` and `svc_delete_user` had no equivalent,
        so the id in the URL walked round a filter applied everywhere else.

    "Only" is load-bearing and was not the first version of this. Reading `fetch_user_org`
    (the first membership row) let an org_admin claim an account by *adding* it to their own
    organisation - the row they added might sort first, and the account's real organisation
    would never be consulted. That is one request, not the three-request chain that made the
    hazard visible. The premise is only trustworthy if it is unanimous: every membership this
    account holds is in the caller's organisation, or the account is not theirs to administer.
    Its other half lives on the write door - `svc_add_org_member` refuses an org_admin who
    tries to add an account another organisation already holds.

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
    org_ids = await fetch_user_org_ids(conn, user_id=target["id"])
    if caller_org is None or org_ids != [caller_org]:
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
