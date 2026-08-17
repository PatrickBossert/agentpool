# api/routers/stakeholders.py
"""CRUD + CSV import for project stakeholders.

Setting a role is a consequence, not a step: the moment any flag other than is_participant
is set on a stakeholder who holds no other role yet AND that person has no login already
linked to this project, an invite goes out (see _issue_invite_if_newly_privileged below). A
role that cannot be delivered - set with no email, or an email that cannot be one - is
refused with 422 rather than stored quietly; see _validate_deliverable_role.

Changing a row's email is a change of person, not a change of detail. It ends the previous
holder's access and begins the new one's, in that order - see _revoke_membership_if_
reassigned and the _is_reassignment conjunct in _issue_invite_if_newly_privileged.

Three authority levels sit on this router, and they are not the same question.

- Reaching a write door at all is `require_project_administration` - platform tier, or
  `project_admin` on this slug.
- Granting `is_project_admin` or `is_governor` through one is the narrower
  `_assert_may_grant_role_flags` - `project_admin` and nothing else, so an org_admin who may
  configure the whole engagement still cannot mint one.
- `POST .../resend-invite` is `require_org_admin_or_above` and is the exception: its response
  body is a redeemable credential, not configuration. See its docstring for the two chains
  that keeps closed.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from api.auth import require_any_auth, require_org_admin_or_above, check_project_access
from api.services.authority_service import (
    caller_may_administer_project,
    caller_may_grant_project_roles,
    require_project_administration,
)
from api.services.stakeholder_service import (
    list_stakeholders,
    create_stakeholder,
    update_stakeholder_svc,
    delete_stakeholder_svc,
    import_csv,
)
# The three conditions this router decides invites by are stated in stakeholder_access and
# imported under their long-standing local names, because the stakeholder read model has to
# report the very same conditions the write doors enforce. Two copies of "holds a role
# beyond participant" is exactly the divergence CLAUDE.md records for register_scripts_sync
# and scripts_awaiting_regeneration.
from api.services.stakeholder_access import (
    ROLE_FLAGS as _ROLE_FLAGS,
    has_deliverable_email as _has_valid_email,
    has_linked_login as _has_linked_login,
    holds_role_beyond_participant as _holds_other_role,
)
from api.services.invite_service import cancel_invite, issue_invite, reissue_invite
from api.database import (
    get_connection,
    get_system_connection,
    delete_project_membership_by_stakeholder,
    fetch_project,
    fetch_stakeholder,
    get_stakeholder_node_assignments,
    upsert_stakeholder_node_assignments,
)

router = APIRouter(prefix="/projects", tags=["stakeholders"])


class StakeholderIn(BaseModel):
    # "allow" rather than "forbid": the frontend's FormData already sends interview_status,
    # interview_invited_at and interview_completed_at, which neither this model nor
    # StakeholderPatch declares. Forbidding all extras would 422 every real save from the
    # UI. _assert_may_grant_role_flags below checks only the two names that matter -
    # is_project_admin and is_governor - which pydantic would otherwise drop silently,
    # and _declared_fields_only is what carries them through to the write.
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
# _ROLE_FLAGS and _holds_other_role are imported above from api/services/stakeholder_access.py,
# which is also what the stakeholder read model answers "can this person get in?" with.

# Real columns (api/database.py), but neither StakeholderIn nor StakeholderPatch declares
# them - see _declared_fields_only for why they stay undeclared, and the models'
# docstrings for why "extra: allow" plus these explicit checks rather than
# "extra: forbid" outright.
_UNDECLARED_ROLE_FLAGS = ("is_project_admin", "is_governor")


def _parse_role_flags(body: BaseModel) -> dict[str, bool]:
    """The supplied is_project_admin / is_governor values, as real booleans, or 422.

    Strict on purpose, and the strictness is the point. These two arrive through
    `extra="allow"` rather than as declared pydantic fields, so nothing has coerced or
    validated them by the time they reach here - `{"is_project_admin": "false"}` is a
    non-empty string, which is *truthy*. Under a plain `bool()` that read as a grant, and for
    a caller entitled to grant it was then written as True: the API would have set the flag
    in response to a body that says, in the only sense a human reads it, not to. A silent
    wrong write, which is the class of defect the rest of this module exists to prevent.

    Accepted: `True`/`False`, and `1`/`0` (JSON has no distinct integer-boolean, and
    `{"is_governor": 0}` is a revocation this API has honoured since sp37's round 3).
    Everything else - strings either way, null, lists - is refused with a 422 that says what
    was sent. A declared `bool` field would give this for free, and cannot be used here: see
    `_declared_fields_only` on what a False default does to a full-replace PUT.
    """
    extra = body.model_extra or {}
    parsed: dict[str, bool] = {}
    for flag in _UNDECLARED_ROLE_FLAGS:
        if flag not in extra:
            continue
        raw = extra[flag]
        if raw is True or raw is False:
            parsed[flag] = raw
        elif isinstance(raw, int) and raw in (0, 1):
            parsed[flag] = bool(raw)
        else:
            raise HTTPException(
                status_code=422,
                detail=f"{flag} must be true or false, not {raw!r}",
            )
    return parsed


def _declared_fields_only(body: BaseModel, **dump_kwargs) -> dict:
    """model_dump(), stripped of whatever extra="allow" let through - except
    is_project_admin/is_governor, which reach the write as the booleans they were sent as.

    The frontend's FormData sends interview_status, interview_invited_at and
    interview_completed_at, which neither model declares - with extra="allow", those would
    otherwise land in the dict unpacked into insert_stakeholder/update_stakeholder as
    **fields. Neither accepts unknown keyword arguments - insert_stakeholder would TypeError,
    update_stakeholder raises ValueError via _STAKEHOLDER_UPDATABLE_FIELDS - so every real
    save from the UI would 500 the moment "allow" was chosen over "ignore" without this.

    is_project_admin/is_governor get special treatment: they are real columns that neither
    model declares, so without this they are dropped on the floor. Until sp44 only their
    *falsy* values were let through, because the guard beside it refused every
    truthy one before this function ever ran and a grant could not exist. It can now, and a
    grant that authorised then silently dropped would be the original defect wearing an
    authority check - a 200 with the flag still false. Both directions pass through, and
    `_assert_may_grant_role_flags` is what decides whether the truthy direction was allowed.

    Values come from `_parse_role_flags`, which refuses anything that is not recognisably a
    boolean rather than coercing it. Revocation is the direction that stays open without an
    authority check; {"is_governor": 0} is a revocation, and review round 3 found that an
    `is False` match here silently dropped it rather than honouring it.

    Declaring the two on StakeholderIn/StakeholderPatch would be tidier and is deliberately
    not done: StakeholderIn drives a full-replace PUT, so a declared field with a False
    default would silently clear both flags on every unrelated PUT that omits them.
    """
    role_flags = _parse_role_flags(body)
    extras = {k: v for k, v in (body.model_extra or {}).items() if k not in role_flags}
    dumped = body.model_dump(exclude=set(extras), **dump_kwargs)
    dumped.update(role_flags)
    return dumped


async def _assert_may_grant_role_flags(slug: str, body: BaseModel, payload: dict) -> None:
    """Granting is_project_admin or is_governor takes project_admin on this project.

    The authority check the previous refusal was waiting for. It used to 422 every truthy
    attempt outright - "cannot be set through this endpoint yet" - which made both roles
    storable, migratable, walkable, reportable and impossible to give to anybody. Bootstrap
    needs no special case: `is_sys_admin` implies `project_admin` on every project (see
    `caller_roles`), so a sysadmin appoints the first one and that one appoints the rest.

    Deliberately narrower than the administration gate on the door itself: an org_admin who
    may configure everything else about this engagement still may not mint a project_admin
    on it. See `caller_may_grant_project_roles`.

    Clearing either flag is deliberately the opposite: permitted without the check,
    API-writable (see _declared_fields_only), and irreversible through this API once done -
    revocation is the safe direction, and it is the repair sp37's review round 2 required so
    an already-undeliverable row (a role, no email) is not locked out of ever losing the role
    that makes it so. That asymmetry is intentional, not an oversight the grant-side refusal
    happens to share.
    """
    # _parse_role_flags, not `extra.get(f)`: the two must agree on what counts as a grant, or
    # a value one reads as True and the other as False is refused by neither and written by
    # both. It also 422s a non-boolean here, before any authority question is asked.
    attempted = [f for f, value in _parse_role_flags(body).items() if value]
    if not attempted:
        return
    if await caller_may_grant_project_roles(slug, payload):
        return
    raise HTTPException(
        status_code=403,
        detail=f"{', '.join(attempted)} may only be granted by a project_admin on this project",
    )


def _normalised_email(flags: dict) -> str:
    """The comparison form of this flag dict's address - stripped and lowercased.

    Not a third convention: `_stakeholder_matches_invite` in `invite_service.py` already
    compares a stakeholder's email against a token's with `.strip().lower()`, and this
    matches it so that "is this the same person" is answered the same way on both sides of
    the invite loop. It matters that it is exactly that and no looser: `users.username` is
    `TEXT UNIQUE` with SQLite's binary collation, so `fetch_user` distinguishes casings the
    rest of the code does not - which is why a casing edit must NOT read as a new person
    here, or it would revoke a live membership and invite an address that already has one.
    """
    return (flags.get("email") or "").strip().lower()


def _is_reassignment(before: dict | None, after: dict) -> bool:
    """Whether this write re-pointed the row at a *different* person.

    Ordinary and routine: "Dougie has left, Sam has the seat now" is an email edit on the
    existing row, keeping the flags, the node assignments and the interview history. What
    it is not is a change of role, so neither `_issue_invite_if_newly_privileged` nor
    `_revoke_membership_if_no_longer_privileged` sees anything happen - both key on the
    role transition. Left at that, the departed holder's login keeps the membership (which
    points at the row by `stakeholder_id`, so an email edit cannot dislodge it) and with it
    full read of the engagement plus every gate that reads `caller_roles`, indefinitely and
    silently, while the arriving holder is never invited.

    A create is not a reassignment - there was no previous holder to displace - and neither
    is a casing or whitespace edit, per `_normalised_email`.
    """
    if not before:
        return False
    return _normalised_email(before) != _normalised_email(after)


def _is_undeliverable(flags: dict) -> bool:
    """Has a role beyond participant, but no address that could actually be delivered to."""
    return _holds_other_role(flags) and not _has_valid_email(flags)


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


async def _issue_invite_if_newly_privileged(slug: str, before: dict | None, after: dict) -> None:
    """Issues the invite the moment the row *becomes* deliverable-and-privileged - holding a
    role beyond participant with a valid email - not only the moment a role first appears,
    and not at all once a login already exists.

    `after` must be both privileged and deliverable, or nothing happens - `_validate_
    deliverable_role` already refuses any write that would leave it privileged with no
    address, so this is mostly a redundant guard, not the load-bearing one.

    Given that, this fires unless `before` was *already* both privileged and deliverable -
    i.e. unless this write left something that was already fully set up untouched. Two
    distinct ways a write can be the one that newly completes that state, both covered by the
    single "was before already both?" check rather than tracked separately:

    - a role newly appears on a person who already had a valid email (the original case: is
      granted a role for the first time);
    - review round 3's repair path - an email newly becomes valid on a person who already
      held a role but had nowhere to deliver to (Dougie McCrone's actual shape: is_reviewer
      already set, email ""). The first version of this predicate only tracked the first
      case, via `had_role` - so PATCHing in a real email for an already-undeliverable row
      passed _validate_deliverable_role (now permitted, per Important 1) but never triggered
      an invite: the guard's own stated invariant, deliverable-and-privileged implies
      invited-or-already-logged-in, was unreachable for the one live row that motivated the
      whole task.

    Adding a *second* role to someone already both privileged and deliverable (is_reviewer
    already true, is_approver newly added) does not re-trigger this, because "before already
    both" is already satisfied - nothing there needed completing.

    A reassignment is the exception to that early return, and the reason for the
    `_is_reassignment` conjunct: when the address changes, "before was already both" was
    true of *somebody else*, so nothing has been set up for the person the row now names.
    They are a fresh grant and are invited as one - the mirror of
    `_revoke_membership_if_reassigned`, which withdraws the departed holder's membership on
    the same transition. Both halves of the handover, or neither: inviting without revoking
    leaves two people with access, and revoking without inviting hands the seat to somebody
    who cannot reach it.

    The login conjunct (_has_linked_login) still guards the case neither branch above can
    see: a role cleared back to participant-only and then re-set on someone who *has* since
    accepted. That write reads as "before was not already both" again (after clearing, before
    held no role), so without this conjunct it would mint a second, unused, seven-day-live
    token onto a login that can already authenticate. If that token were ever delivered,
    accept_token's existing-user branch runs `UPDATE users SET hashed_pw=?` - an unsolicited
    password-reset credential, created by nothing more than an administrator toggling a
    checkbox, with no audit entry and no notification to the person it targets.
    """
    if not (_holds_other_role(after) and _has_valid_email(after)):
        return
    before = before or {}
    if (
        _holds_other_role(before)
        and _has_valid_email(before)
        and not _is_reassignment(before, after)
    ):
        return
    if await _has_linked_login(slug, after["email"]):
        return
    await issue_invite(email=after["email"], project_slug=slug, stakeholder_id=after["id"])


async def _revoke_membership(slug: str, stakeholder_id: int) -> None:
    """Cut this stakeholder row's link to whatever login reaches the project through it.

    The users row is left alone on purpose. It is a global login that may hold
    memberships on other engagements, and deleting it would revoke those too - the
    membership is what is project-scoped, so the membership is what is withdrawn.
    """
    async with get_system_connection() as conn:
        await delete_project_membership_by_stakeholder(
            conn, project_slug=slug, stakeholder_id=stakeholder_id
        )


async def _revoke_membership_if_reassigned(
    slug: str, before: dict | None, after: dict
) -> None:
    """A seat handover withdraws the departed holder's access.

    `_revoke_membership_if_no_longer_privileged` below fires on a *role* transition, and an
    administrator re-pointing a row at a different person changes only the email - the flags
    stay exactly as they were, so nothing there fires. The membership points at the row by
    `stakeholder_id` (deliberately, so an edited email cannot orphan it), which means the
    departed holder's login keeps reaching the engagement through a row that no longer
    describes them: full read plus every gate `caller_roles` answers, with nothing in the
    system left saying they were ever there.

    Keyed on `stakeholder_id` for the same reason the flag-clearing revocation is: this is
    the link `caller_roles` walks, so it is the link revocation has to cut. The `users` row
    is untouched - it is a global login that may hold memberships on other engagements.

    Any live invite the departed holder still held is already dead without being deleted:
    `_stakeholder_matches_invite` re-reads the stakeholder row's own email when the token is
    redeemed and refuses a token whose address no longer matches it.
    """
    if not _is_reassignment(before, after):
        return
    await _revoke_membership(slug, after["id"])


async def _revoke_membership_if_no_longer_privileged(
    slug: str, before: dict | None, after: dict
) -> None:
    """The mirror of _issue_invite_if_newly_privileged: clearing the last non-participant
    flag takes the access away that setting the first one granted.

    Without this, "clearing every non-participant flag revokes access" was true of
    caller_roles - which correctly returns nothing once the flags are gone - and false of
    the system. check_project_access asks project_memberships, not stakeholders, and it
    has no role test at all, so a revoked person kept full read of the engagement and
    every write door behind membership alone. The design says the flags are the
    revocation; this is what makes the sentence true.

    Fires on the transition only, exactly as the invite side does: was privileged before,
    is not now. A row that was already participant-only is left alone - it never had a
    membership from this route to withdraw - and a partial revocation that still leaves
    some other role standing is not a revocation.

    Both halves of the access, or neither. The membership is what a login already holds;
    the outstanding invite is what a login could be *made* from, and `POST /auth/accept`
    needs no authentication to make one. Cutting only the membership left the credential
    alive on a row the administrator had just revoked - and left the roster reporting that
    person as "Invited", one click from handing it back. See `cancel_invite`.
    """
    if not _holds_other_role(before or {}):
        return
    if _holds_other_role(after):
        return
    await _revoke_membership(slug, after["id"])
    await cancel_invite(after["email"], slug)


@router.get("/{slug}/stakeholders")
async def list_stakeholders_endpoint(slug: str, payload: dict = Depends(require_any_auth)):
    """The roster. Readable by any member of the engagement - membership is read access by
    design - but the three `access_state` values that are answered by looking an account up
    are served only to a caller who may administer the roster.

    Not `require_project_administration`: this door itself does not narrow, and turning a
    reviewer's roster into a 403 would be a much larger change than the disclosure warrants.
    The field is dropped from the response instead, which is why the decision is made here
    and passed down rather than left to the client - a value the client hides is still on
    the wire.
    """
    await check_project_access(slug, payload)
    result = await list_stakeholders(
        slug,
        include_account_states=await caller_may_administer_project(slug, payload),
    )
    if result is None:
        _404(slug)
    return result


# IMPORTANT: /import must be registered BEFORE /{stakeholder_id} routes
@router.post("/{slug}/stakeholders/import")
async def import_stakeholders_endpoint(slug: str, file: UploadFile = File(...), payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    await require_project_administration(slug, payload)
    content = (await file.read()).decode("utf-8", errors="replace")
    result = await import_csv(slug, content)
    if result is None:
        _404(slug)
    return result


@router.post("/{slug}/stakeholders", status_code=201)
async def create_stakeholder_endpoint(slug: str, body: StakeholderIn, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    await require_project_administration(slug, payload)
    await _assert_may_grant_role_flags(slug, body, payload)
    data = _declared_fields_only(body)
    _validate_deliverable_role(None, data)
    result = await create_stakeholder(slug, data)
    if result is None:
        _404(slug)
    await _issue_invite_if_newly_privileged(slug, None, result)
    return result


@router.put("/{slug}/stakeholders/{stakeholder_id}")
async def update_stakeholder_endpoint(slug: str, stakeholder_id: int, body: StakeholderIn, payload: dict = Depends(require_any_auth)):
    await check_project_access(slug, payload)
    await require_project_administration(slug, payload)
    await _assert_may_grant_role_flags(slug, body, payload)
    before = await _fetch_stakeholder_row(slug, stakeholder_id)
    data = _declared_fields_only(body)
    # PUT is a full replace of every field StakeholderIn declares, but is_project_admin and
    # is_governor are not among them - a PUT that omits them leaves both columns alone, and
    # carrying `before`'s values into the merge (validating that, not the bare body) is what
    # stops an unrelated PUT from walking around the 422 that create/PATCH already enforce
    # for the exact same effective state. A PUT that *sends* either flag overrides it, having
    # passed _assert_may_grant_role_flags above.
    effective = {**before, **data} if before else data
    _validate_deliverable_role(before, effective)
    result = await update_stakeholder_svc(slug, stakeholder_id, data)
    if result is None:
        raise HTTPException(status_code=404, detail="Stakeholder not found")
    # Revocation before invitation: the departed holder's link is cut first, so the invite
    # decision below reads a system in which only the arriving holder's own logins count.
    await _revoke_membership_if_reassigned(slug, before, result)
    await _issue_invite_if_newly_privileged(slug, before, result)
    await _revoke_membership_if_no_longer_privileged(slug, before, result)
    return result


@router.patch("/{slug}/stakeholders/{stakeholder_id}")
async def patch_stakeholder_endpoint(slug: str, stakeholder_id: int, body: StakeholderPatch, payload: dict = Depends(require_any_auth)):
    """Partial update - only the fields the caller actually sent are changed. This is what
    lets a second role be granted (e.g. adding is_approver to an existing reviewer) without
    resending the whole record, and it is the write _issue_invite_if_newly_privileged must
    treat as a no-op rather than a second invite."""
    await check_project_access(slug, payload)
    await require_project_administration(slug, payload)
    await _assert_may_grant_role_flags(slug, body, payload)
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
    await _revoke_membership_if_reassigned(slug, before, result)
    await _issue_invite_if_newly_privileged(slug, before, result)
    await _revoke_membership_if_no_longer_privileged(slug, before, result)
    return result


@router.post("/{slug}/stakeholders/{stakeholder_id}/resend-invite")
async def resend_invite_endpoint(
    slug: str, stakeholder_id: int, payload: dict = Depends(require_org_admin_or_above)
):
    """The counterpart nothing provided before this task: an operator's way to re-send a
    lost or expired invite, since _issue_invite_if_newly_privileged only ever fires once per
    grant.

    **PLATFORM TIER, alone among this router's doors, and it must stay that way.** sp44 moved
    the other six onto `require_project_administration` and briefly moved this one too. It is
    not project configuration; it is a credential factory. The response body *is* a
    redeemable token, and `POST /auth/accept` is unauthenticated, so whoever can call this can
    mint a login. Two chains a `project_admin` could otherwise have run, both driven in
    `tests/test_grantable_roles.py`:

    A. Create a stakeholder `{email: ghost@evil.test, is_reviewer: true}` - which they may,
       and should be able to - then resend, redeem the returned token at `/auth/accept` with
       a password of their choosing, and hold a live session for an account they own.
    B. The same, naming a *real* person who has no login yet. A consultant later invites that
       person onto a **different** engagement. The victim redeems it; `accept_token` correctly
       refuses to touch the password and correctly mints no session - **and still writes the
       `project_memberships` row**, because for a known email an invite is a membership grant.
       The attacker, who holds that account's password, now reads the second engagement.

    Chain B is the one that matters: it crosses a project boundary using only doors that are
    individually behaving correctly, which is the shape sp42 closed one layer up. Suppressing
    the token in the response is *not* the fix - retrieving the token is the door's entire
    purpose, and a door that mints an invite for an arbitrary address is the hazard whether or
    not this particular handler hands it back. A project_admin may still create a stakeholder
    with a role; the invite is issued by `_issue_invite_if_newly_privileged` as always, and
    they simply cannot retrieve it.

    Reuses reissue_invite - passing project_slug explicitly so the "nothing to refresh" vs.
    "ambiguous, which project" conflation documented on reissue_invite itself cannot arise
    from this call site: the slug is already known from the URL, not guessed from a bare
    email.

    Returns the raw token in the response rather than emailing it: this branch has no wired
    outbound-email path for invites (Resend is used elsewhere for interview links, not this),
    and building one is a larger change than a resend button warrants. Note too that there is
    no page anywhere in ui/src that redeems a token - /auth/accept exists on the API only, so
    "deliver it by hand" currently describes a link with nowhere to send someone.

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
async def delete_stakeholder_endpoint(slug: str, stakeholder_id: int, payload: dict = Depends(require_any_auth)):
    """Remove the person record - and with it, any login that reached this project
    through it.

    Deleting the row on its own left the membership behind pointing at a stakeholder_id
    that no longer exists: caller_roles then found no stakeholder and returned nothing,
    while check_project_access still passed on the membership. A dangling id with a live
    login attached, holding read of the whole engagement.
    """
    await check_project_access(slug, payload)
    await require_project_administration(slug, payload)
    result = await delete_stakeholder_svc(slug, stakeholder_id)
    if result is None:
        _404(slug)
    if result is False:
        raise HTTPException(status_code=404, detail="Stakeholder not found")
    await _revoke_membership(slug, stakeholder_id)


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
    payload: dict = Depends(require_any_auth),
):
    """Replace all stakeholder-node assignments for a project."""
    await check_project_access(slug, payload)
    await require_project_administration(slug, payload)
    async with get_connection(slug) as conn:
        project = await fetch_project(conn, slug=slug)
        if not project:
            _404(slug)
        assignments = [a.model_dump() for a in body.assignments]
        await upsert_stakeholder_node_assignments(conn, project["id"], assignments)
        return {"count": len(assignments)}
