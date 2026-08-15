# api/routers/stakeholders.py
"""CRUD + CSV import for project stakeholders.

Setting a role is a consequence, not a step: the moment any flag other than is_participant
is set on a stakeholder who holds no other role yet AND that person has no login already
linked to this project, an invite goes out (see _issue_invite_if_newly_privileged below). A
role that cannot be delivered - set with no email, or an email that cannot be one - is
refused with 422 rather than stored quietly; see _validate_deliverable_role.
"""
import re

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from api.auth import require_any_auth, require_org_admin_or_above, check_project_access
from api.services.stakeholder_service import (
    list_stakeholders,
    create_stakeholder,
    update_stakeholder_svc,
    delete_stakeholder_svc,
    import_csv,
)
from api.services.invite_service import issue_invite, reissue_invite
from api.database import (
    get_connection,
    get_system_connection,
    fetch_project,
    fetch_stakeholder,
    fetch_user,
    get_stakeholder_node_assignments,
    upsert_stakeholder_node_assignments,
)

router = APIRouter(prefix="/projects", tags=["stakeholders"])


class StakeholderIn(BaseModel):
    # "allow" rather than "forbid": the frontend's FormData already sends interview_status,
    # interview_invited_at and interview_completed_at, which neither this model nor
    # StakeholderPatch declares. Forbidding all extras would 422 every real save from the
    # UI. _reject_undeclared_role_flags below checks only the two names that matter -
    # is_project_admin and is_governor - which pydantic would otherwise drop silently.
    model_config = {"extra": "allow"}

    name: str
    job_title: str = ""
    organisation: str = ""
    email: str = ""
    slack_handle: str = ""
    stakeholder_groups: list[str] = []
    project_role: str = "recipient"
    value_streams: list[str] = []
    value_chain_stage: str = ""
    activity: str = ""
    disposition: str = "neutral"
    location: str = ""
    country_code: str = ""
    timezone: str = ""
    preferred_language: str = ""
    currency: str = ""
    level: str = ""
    entity: str = ""
    mobile: str = ""
    comms_channel: str = "email"
    is_participant: bool = False
    is_reviewer: bool = False
    is_approver: bool = False


class StakeholderPatch(BaseModel):
    """Partial update - only fields actually supplied (model_dump(exclude_unset=True,
    exclude_none=True)) are changed. Unlike StakeholderIn's full-replace PUT, `name` is not
    required here. An explicit null for any field is treated the same as omitting it, not as
    "clear this column" - every column here is NOT NULL, so a client sending
    {"email": null} (routine for a form field being cleared) would otherwise 500."""
    model_config = {"extra": "allow"}

    name: str | None = None
    job_title: str | None = None
    organisation: str | None = None
    email: str | None = None
    slack_handle: str | None = None
    stakeholder_groups: list[str] | None = None
    project_role: str | None = None
    value_streams: list[str] | None = None
    value_chain_stage: str | None = None
    activity: str | None = None
    disposition: str | None = None
    location: str | None = None
    country_code: str | None = None
    timezone: str | None = None
    preferred_language: str | None = None
    currency: str | None = None
    level: str | None = None
    entity: str | None = None
    mobile: str | None = None
    comms_channel: str | None = None
    is_participant: bool | None = None
    is_reviewer: bool | None = None
    is_approver: bool | None = None


class NodeAssignmentItem(BaseModel):
    stakeholder_id: int
    node_key: str


class NodeAssignmentsIn(BaseModel):
    assignments: list[NodeAssignmentItem] = []


def _404(slug: str):
    raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")


# Every role but participant confers some form of administration or review authority, so any
# of these being set is what makes a stakeholder somebody who needs a way to log in.
_ROLE_FLAGS = ("is_reviewer", "is_approver", "is_project_admin", "is_governor")

# Real columns (api/database.py), but neither StakeholderIn nor StakeholderPatch declares
# them yet - see the models' docstrings for why "extra: allow" plus this explicit check,
# rather than "extra: forbid" outright.
_UNDECLARED_ROLE_FLAGS = ("is_project_admin", "is_governor")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _holds_other_role(flags: dict) -> bool:
    """Whether any role beyond is_participant is set on this (possibly partial) flag dict."""
    return any(flags.get(f) for f in _ROLE_FLAGS)


def _declared_fields_only(body: BaseModel, **dump_kwargs) -> dict:
    """model_dump(), stripped of whatever extra="allow" let through - except an explicit
    False for is_project_admin/is_governor, which must still reach the write.

    The frontend's FormData sends interview_status, interview_invited_at and
    interview_completed_at, which neither model declares - with extra="allow", those would
    otherwise land in the dict unpacked into insert_stakeholder/update_stakeholder as
    **fields. Neither accepts unknown keyword arguments - insert_stakeholder would TypeError,
    update_stakeholder raises ValueError via _STAKEHOLDER_UPDATABLE_FIELDS - so every real
    save from the UI would 500 the moment "allow" was chosen over "ignore" without this.

    is_project_admin/is_governor get special treatment: _reject_undeclared_role_flags already
    guarantees a truthy attempt at either never reaches this function, so anything left here
    is an explicit False - revoking a role that was seeded outside the API (e.g. directly in
    the database, or before this task existed) is the natural repair for a row Important-1's
    guard would otherwise refuse to touch, and dropping it here would refuse that repair
    silently while returning 200 - the exact regression review round 2 found.
    """
    extras = dict(body.model_extra or {})
    revocations = {f: extras.pop(f) for f in _UNDECLARED_ROLE_FLAGS
                   if extras.get(f) is False}
    dumped = body.model_dump(exclude=set(extras), **dump_kwargs)
    dumped.update(revocations)
    return dumped


def _reject_undeclared_role_flags(body: BaseModel) -> None:
    """is_project_admin and is_governor used to be silently dropped - a POST of
    {"is_governor": true} returned 201 with is_governor still false, and nothing told the
    caller their request was ignored. Neither model supports setting them yet (that needs an
    authority check this task does not build), so the write is refused loudly instead."""
    extra = body.model_extra or {}
    attempted = [f for f in _UNDECLARED_ROLE_FLAGS if extra.get(f)]
    if attempted:
        raise HTTPException(
            status_code=422,
            detail=f"{', '.join(attempted)} cannot be set through this endpoint yet",
        )


def _is_undeliverable(flags: dict) -> bool:
    """Has a role beyond participant, but no address that could actually be delivered to."""
    if not _holds_other_role(flags):
        return False
    email = (flags.get("email") or "").strip()
    return not email or not _EMAIL_RE.match(email)


def _validate_deliverable_role(before: dict | None, effective: dict) -> None:
    """Refuse a write that INTRODUCES the undeliverable state - a role with no address that
    could be delivered to - not one that merely leaves an already-undeliverable row alone, or
    repairs it.

    Dougie McCrone's row already exists in this state on the live project. The first version
    of this guard refused every write that merely left an already-bad row bad, which - because
    it validated the merged effective state, not the transition into it - locked his row out
    of every edit whatsoever: a job-title-only PATCH 422'd quoting "email is required", and a
    PUT actually revoking the role that made his row undeliverable was refused for the very
    reason it was trying to fix. That is worse than doing nothing: it turns a data-quality
    problem into one only a direct database edit can repair.

    So this only refuses when the write makes things worse than they were:
    - `before` is None (create) - any undeliverable state is new, refuse unconditionally.
    - `before` was already deliverable and `effective` is not - the write broke it (cleared
      or corrupted the email, or added a role with none), refuse.
    - `before` was already undeliverable and `effective` still is, but this write adds a role
      that was not already set - "adds a role to a person with no email" is still refused
      even though the row is not new, since it is still a role newly created with nowhere to
      deliver it.
    - `before` was already undeliverable and `effective` still is, but every role flag that
      was set before is still set (nothing added) - permitted. Covers an unrelated field edit
      (job title) and a partial revocation that still leaves some other role standing.
    """
    if not _is_undeliverable(effective):
        return
    if before is not None and _is_undeliverable(before):
        newly_added_role = any(effective.get(f) and not before.get(f) for f in _ROLE_FLAGS)
        if not newly_added_role:
            return
    email = (effective.get("email") or "").strip()
    if not email:
        raise HTTPException(
            status_code=422,
            detail="email is required to invite a stakeholder holding a role beyond participant",
        )
    raise HTTPException(
        status_code=422,
        detail="email must be a valid address to invite a stakeholder holding a role "
               "beyond participant",
    )


async def _fetch_stakeholder_row(slug: str, stakeholder_id: int) -> dict | None:
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            return None
        return await fetch_stakeholder(conn, stakeholder_id=stakeholder_id, project_id=project["id"])


async def _has_linked_login(slug: str, email: str) -> bool:
    """Whether this email already has a login linked to *this* project.

    Scoped to (email, slug) via project_memberships - not merely "does this email have a
    login anywhere" - because project_memberships.stakeholder_id is what "one login, many
    engagements" is built on (see invite_service.py and
    tests/test_invite_loop.py::test_inviting_the_same_person_to_a_second_project_keeps_both_live):
    someone already logged in on one project must still be invitable onto a second one. A
    login is created only when an invite is accepted, so this is a real, unmocked read - see
    _issue_invite_if_newly_privileged for why it must be conjoined with, not replace, the
    transition check.
    """
    async with get_system_connection() as conn:
        user = await fetch_user(conn, username=email)
        if user is None:
            return False
        cur = await conn.execute(
            "SELECT 1 FROM project_memberships WHERE user_id=? AND project_slug=?",
            (user["id"], slug),
        )
        return await cur.fetchone() is not None


async def _issue_invite_if_newly_privileged(slug: str, before: dict | None, after: dict) -> None:
    """Setting any role other than participant on somebody with no linked login issues the
    invite - the moment it is first set, not on every later write that touches the row, and
    not at all once a login already exists.

    Two independent conditions, both required:

    - "newly set" - `before` held no role beyond participant. Required even though issuing
      an invite never creates a login (only accept_token does, on acceptance): without this,
      adding a second role to an already-invited-but-not-yet-accepted stakeholder (is_reviewer
      already true, is_approver newly added) would fire a second time, since nothing else
      changed in between.
    - "no linked login yet" - _has_linked_login is false. Required for the case the first
      condition alone cannot see: a role cleared back to participant-only and then re-set on
      someone who *has* since accepted. Without this conjunct, that write reads as "newly
      set" again and mints a second, unused, seven-day-live token onto a login that can
      already authenticate. If that token were ever delivered, accept_token's existing-user
      branch runs `UPDATE users SET hashed_pw=?` - an unsolicited password-reset credential,
      created by nothing more than an administrator toggling a checkbox, with no audit entry
      and no notification to the person it targets.
    """
    if not _holds_other_role(after):
        return
    had_role = _holds_other_role(before) if before else False
    if had_role:
        return
    if await _has_linked_login(slug, after["email"]):
        return
    await issue_invite(email=after["email"], project_slug=slug, stakeholder_id=after["id"])


@router.get("/{slug}/stakeholders")
async def list_stakeholders_endpoint(slug: str, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    result = await list_stakeholders(slug)
    if result is None:
        _404(slug)
    return result


# IMPORTANT: /import must be registered BEFORE /{stakeholder_id} routes
@router.post("/{slug}/stakeholders/import")
async def import_stakeholders_endpoint(slug: str, file: UploadFile = File(...), payload: dict = Depends(require_org_admin_or_above)):
    await check_project_access(slug, payload)
    content = (await file.read()).decode("utf-8", errors="replace")
    result = await import_csv(slug, content)
    if result is None:
        _404(slug)
    return result


@router.post("/{slug}/stakeholders", status_code=201)
async def create_stakeholder_endpoint(slug: str, body: StakeholderIn, payload: dict = Depends(require_org_admin_or_above)):
    await check_project_access(slug, payload)
    _reject_undeclared_role_flags(body)
    data = _declared_fields_only(body)
    _validate_deliverable_role(None, data)
    result = await create_stakeholder(slug, data)
    if result is None:
        _404(slug)
    await _issue_invite_if_newly_privileged(slug, None, result)
    return result


@router.put("/{slug}/stakeholders/{stakeholder_id}")
async def update_stakeholder_endpoint(slug: str, stakeholder_id: int, body: StakeholderIn, payload: dict = Depends(require_org_admin_or_above)):
    await check_project_access(slug, payload)
    _reject_undeclared_role_flags(body)
    before = await _fetch_stakeholder_row(slug, stakeholder_id)
    data = _declared_fields_only(body)
    # PUT is a full replace of every field StakeholderIn declares, but is_project_admin and
    # is_governor are not among them - carrying `before`'s values forward for those two (and
    # validating the merge, not the bare body) is what stops an unrelated PUT from either
    # silently clearing them or walking around the 422 that create/PATCH already enforce for
    # the exact same effective state.
    effective = {**before, **data} if before else data
    _validate_deliverable_role(before, effective)
    result = await update_stakeholder_svc(slug, stakeholder_id, data)
    if result is None:
        raise HTTPException(status_code=404, detail="Stakeholder not found")
    await _issue_invite_if_newly_privileged(slug, before, result)
    return result


@router.patch("/{slug}/stakeholders/{stakeholder_id}")
async def patch_stakeholder_endpoint(slug: str, stakeholder_id: int, body: StakeholderPatch, payload: dict = Depends(require_org_admin_or_above)):
    """Partial update - only the fields the caller actually sent are changed. This is what
    lets a second role be granted (e.g. adding is_approver to an existing reviewer) without
    resending the whole record, and it is the write _issue_invite_if_newly_privileged must
    treat as a no-op rather than a second invite."""
    await check_project_access(slug, payload)
    _reject_undeclared_role_flags(body)
    before = await _fetch_stakeholder_row(slug, stakeholder_id)
    if before is None:
        raise HTTPException(status_code=404, detail="Stakeholder not found")
    # exclude_none as well as exclude_unset: every column here is NOT NULL, so an explicit
    # {"email": null} - routine for a client clearing a form field - must be treated the same
    # as omitting the key, not as "write NULL" (IntegrityError) or "write empty string"
    # unasked. See Important 3 in the review this responds to.
    patch_fields = _declared_fields_only(body, exclude_unset=True, exclude_none=True)
    if not patch_fields:
        return before
    effective = {**before, **patch_fields}
    _validate_deliverable_role(before, effective)
    result = await update_stakeholder_svc(slug, stakeholder_id, patch_fields)
    if result is None:
        raise HTTPException(status_code=404, detail="Stakeholder not found")
    await _issue_invite_if_newly_privileged(slug, before, result)
    return result


@router.post("/{slug}/stakeholders/{stakeholder_id}/resend-invite")
async def resend_invite_endpoint(slug: str, stakeholder_id: int, payload: dict = Depends(require_org_admin_or_above)):
    """The counterpart nothing provided before this task: an operator's way to re-send a
    lost or expired invite, since _issue_invite_if_newly_privileged only ever fires once per
    grant.

    Reuses reissue_invite - the function this branch already carries for exactly this,
    flagged in Task 6 as having no caller yet - passing project_slug explicitly so the
    "nothing to refresh" vs. "ambiguous, which project" conflation documented on
    reissue_invite itself cannot arise from this call site: the slug is already known from
    the URL, not guessed from a bare email.

    Returns the raw token in the response rather than emailing it: this branch has no wired
    outbound-email path for invites (Resend is used elsewhere for interview links, not this),
    and building one is a larger change than a resend button warrants. Note too that there is
    no page anywhere in ui/src that redeems a token - /auth/accept exists on the API only, so
    "deliver it by hand" currently describes a link with nowhere to send someone. Building
    that redemption page is Task 8's job, not this one's.

    _has_linked_login guards this the same way it guards _issue_invite_if_newly_privileged,
    and for the same reason: reissuing mints a fresh token regardless of whether the old one
    was ever used, and delivering it to someone who can already log in on this project would
    let accept_token's existing-user branch silently overwrite their password. Without this,
    an explicit resend was a second, milder door to the exact hazard the write-triggered path
    already closed - milder only because it needs a deliberate operator action rather than a
    checkbox toggle, not because the consequence differs.
    """
    await check_project_access(slug, payload)
    row = await _fetch_stakeholder_row(slug, stakeholder_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Stakeholder not found")
    email = (row.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=422, detail="email is required to resend an invite")
    if await _has_linked_login(slug, email):
        raise HTTPException(
            status_code=409,
            detail="this person already has a login linked to this project - nothing to resend",
        )
    raw = await reissue_invite(email, project_slug=slug)
    if raw is None:
        raise HTTPException(status_code=404, detail="No live invite to resend for this stakeholder")
    return {"invite_token": raw}


@router.delete("/{slug}/stakeholders/{stakeholder_id}", status_code=204)
async def delete_stakeholder_endpoint(slug: str, stakeholder_id: int, payload: dict = Depends(require_org_admin_or_above)):
    await check_project_access(slug, payload)
    result = await delete_stakeholder_svc(slug, stakeholder_id)
    if result is None:
        _404(slug)
    if result is False:
        raise HTTPException(status_code=404, detail="Stakeholder not found")


@router.get("/{slug}/stakeholder-assignments")
async def get_stakeholder_assignments_endpoint(slug: str, payload: dict = Depends(require_any_auth)):
    """Return all stakeholder-node assignments for a project."""
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            _404(slug)
        return await get_stakeholder_node_assignments(conn, project["id"])


@router.put("/{slug}/stakeholder-assignments")
async def put_stakeholder_assignments_endpoint(
    slug: str,
    body: NodeAssignmentsIn,
    payload: dict = Depends(require_org_admin_or_above),
):
    """Replace all stakeholder-node assignments for a project."""
    await check_project_access(slug, payload)
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            _404(slug)
        assignments = [a.model_dump() for a in body.assignments]
        await upsert_stakeholder_node_assignments(conn, project["id"], assignments)
        return {"count": len(assignments)}
