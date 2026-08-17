# api/services/stakeholder_access.py
"""Whether a stakeholder can actually reach this engagement - and if not, why not.

The stakeholder list showed role flags and nothing else, so a person holding reviewer and
approver with an empty email rendered identically to one who logs in every morning. That
row existed on a live project for weeks: it could exercise neither role, and nothing
anywhere said so. This is the read model that says which.

The states, in the order they are decided:

  has_login        a login linked to *this* project - the same question
                   `_issue_invite_if_newly_privileged` and the resend door ask before they
                   act.
  no_login_needed  no role beyond participant. Asked *before* the invite question, so a
                   revoked row can never read as invited even if its token outlived the
                   revocation - see `access_state`.
  invited          an unredeemed invite to this project exists. Exactly the set
                   `reissue_invite` can refresh, so it is also the set for which the
                   "issue an invite link" action can succeed.
  unreachable      holds a role beyond participant with no address that could be delivered
                   to. The state that motivated all this.
  not_invited      holds a deliverable role, has neither a login nor an invite. Not one of
                   the four states the design enumerated, and it is not decoration: every
                   role granted before sp41 wired `_issue_invite_if_newly_privileged` has
                   this shape, and so does a row whose login was later deleted. Calling it
                   `invited` would be a read model that lies about precisely the rows an
                   administrator is looking for, and calling it `unreachable` would blame
                   an address that is perfectly good.

Participants answer interviews through a campaign link and need no login by design, which
is why `no_login_needed` is a resting state rather than an omission.

Two comparisons matter and both are deliberately exact rather than case-folded: the doors
that act on these answers (`has_linked_login` below, `issue_invite`, `reissue_invite`) find
a login by `users.username`, which is TEXT UNIQUE under SQLite's binary collation. A read
model that matched more loosely than the door would report access nobody has.
"""
import re

from api.database import (
    fetch_open_invite_emails,
    fetch_project_login_emails,
    get_system_connection,
)

# Every role flag other than is_participant. Holding any of them is what makes a login
# necessary, which is why the tuple is stated once and imported everywhere it is asked -
# api/routers/stakeholders.py binds it as _ROLE_FLAGS.
ROLE_FLAGS = ("is_reviewer", "is_approver", "is_project_admin", "is_governor")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

HAS_LOGIN = "has_login"
INVITED = "invited"
UNREACHABLE = "unreachable"
NOT_INVITED = "not_invited"
NO_LOGIN_NEEDED = "no_login_needed"

ACCESS_STATES = (HAS_LOGIN, INVITED, UNREACHABLE, NOT_INVITED, NO_LOGIN_NEEDED)


def holds_role_beyond_participant(flags: dict) -> bool:
    """Whether any role beyond is_participant is set on this (possibly partial) flag dict."""
    return any(flags.get(f) for f in ROLE_FLAGS)


def has_deliverable_email(flags: dict) -> bool:
    """Whether this flag dict's email is present and looks like an address - deliverability
    in isolation, independent of whether a role is held. `_is_undeliverable` in the router is
    this combined with holds_role_beyond_participant; `_issue_invite_if_newly_privileged`
    needs the two apart, since a row can go from role-with-no-email to role-with-email
    without ever losing the role, and that transition is itself what must trigger the
    invite."""
    email = (flags.get("email") or "").strip()
    return bool(email) and bool(_EMAIL_RE.match(email))


def access_state(row: dict, *, login_emails: set[str], invited_emails: set[str]) -> str:
    """Which of ACCESS_STATES this stakeholder row is in. Exactly one, always.

    `login_emails` and `invited_emails` are read once for the whole list rather than per
    row - see `annotate_access_state`. The address is stripped before either lookup because
    that is what the resend door does before asking the same two questions.

    **The role check outranks the invite check, and that ordering is a guard rather than a
    preference.** Clearing every non-participant flag is the documented revocation, and
    `cancel_invite` now kills the outstanding token as part of it - but a token that
    survived by some other path (a write that never reached the router, a row restored from
    a backup, a future caller of `issue_invite` that forgets) would otherwise make a
    role-less row read `invited`, which puts the "issue an invite link" action in front of
    an administrator who has *just revoked this person* and hands the access straight back.
    The repair and the guard fail differently, so both exist: this ordering holds even when
    the cancellation does not run.

    A login is asked about before either, and is not subordinated to the role check: a
    membership on this project is access somebody actually holds, whatever their flags say
    now. Revocation deletes that membership, so a revoked person does not linger here
    either.
    """
    email = (row.get("email") or "").strip()
    if email and email in login_emails:
        return HAS_LOGIN
    if not holds_role_beyond_participant(row):
        return NO_LOGIN_NEEDED
    if email and email in invited_emails:
        return INVITED
    if not has_deliverable_email(row):
        return UNREACHABLE
    return NOT_INVITED


async def annotate_access_state(slug: str, rows: list[dict]) -> list[dict]:
    """Return `rows` with `access_state` on each. Two system-database reads for the list.

    The client cannot derive any of this: `auth_tokens` and `project_memberships` live in
    system.db and no endpoint exposes either, so "invited" is not merely inconvenient to
    compute in the browser but unknowable there. Deriving "unreachable" from an empty email
    string alone *would* be possible, and would still be wrong - it would put the same
    condition in a second place, where it could disagree with the 422 the write doors raise.
    """
    if not rows:
        return rows
    async with get_system_connection() as conn:
        login_emails = await fetch_project_login_emails(conn, project_slug=slug)
        invited_emails = await fetch_open_invite_emails(conn, project_slug=slug)
    for row in rows:
        row["access_state"] = access_state(
            row, login_emails=login_emails, invited_emails=invited_emails
        )
    return rows


async def has_linked_login(slug: str, email: str) -> bool:
    """Whether this email already has a login linked to *this* project.

    Scoped to (email, slug) via project_memberships - not merely "does this email have a
    login anywhere" - because project_memberships.stakeholder_id is what "one login, many
    engagements" is built on (see invite_service.py and
    tests/test_invite_loop.py::test_inviting_the_same_person_to_a_second_project_keeps_both_live):
    someone already logged in on one project must still be invitable onto a second one. A
    login is created only when an invite is accepted, so this is a real, unmocked read - see
    `_issue_invite_if_newly_privileged` for why it must be conjoined with, not replace, the
    transition check.

    Shares `fetch_project_login_emails` with the list read model above so the badge a
    stakeholder is shown under and the guard that refuses to re-invite them are one rule
    rather than two copies of it.
    """
    async with get_system_connection() as conn:
        return email in await fetch_project_login_emails(conn, project_slug=slug)
