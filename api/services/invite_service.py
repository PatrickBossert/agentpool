# api/services/invite_service.py
"""Invite, accept, and reset - how somebody gets a login.

One token table backs both purposes: an 'invite' creates the users row and the project
membership together; a 'reset' only replaces the password on a login that already exists,
which is why its token carries no project_slug or stakeholder_id.

Tokens are hashed with a fast deterministic digest (sha256), not bcrypt. bcrypt is a slow KDF
- the right tool for a low-entropy secret a human chose, because slowness is what makes
guessing expensive. A token from secrets.token_urlsafe(32) is 256 bits of randomness; nothing
is gained by slowing down its hash, and everything is lost by doing so inside an unauthenticated
request handler: bcrypt's random salt means the same raw value hashes to a different string
every time, so a lookup can only be done by re-hashing and comparing candidate rows in a loop.
On this table that loop runs against every *unused* row for every accept, unauthenticated and
unrated - forty ordinary outstanding invites (the expected shape of "one live invite per
person") turned a single /auth/accept call into a 13-second, event-loop-blocking scan that
stalled the whole API for every other request in flight. sha256 gives an indexed
`WHERE token_hash = ?` equality lookup instead - the token_hash column's UNIQUE constraint
already carries an index, so this is a single-row fetch regardless of table size. Raw tokens
are still never stored or logged; only their digest is.

Re-issuing an invite necessarily mints a brand new token onto the same row rather than
resending the original: a hash cannot be reversed to recover what was sent, and a lost email
should stay dead. One live invite is kept per (person, project) - not per person - since a
second invite for a different engagement must not silently overwrite the first one's
project_slug and stakeholder_id.

accept_token is the main caller of link_membership. project_memberships.stakeholder_id lives
in system.db while the stakeholder itself lives in the project's own database, so no foreign
key can catch a mismatch - and stakeholder ids restart at 1 in every project file, so an id
that resolves to *someone* is the ordinary case, not the exceptional one. Existence alone is
not proof of identity: checking only "does this id exist on this project" passes for another
stakeholder's id just as readily as for the intended one. The token also carries the email it
was issued to, so accept_token compares that email against the resolved stakeholder's own
email and refuses the entire acceptance - no login, no membership, token left live - on any
mismatch, rather than degrading to a login with no rights. That leaves room for the invite to
be corrected and re-issued; stamping the token used on a refused link would have destroyed
that path along with the wrong one.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from api.auth import hash_password
from api.database import (
    get_connection,
    get_db_path,
    get_system_connection,
    fetch_project,
    fetch_stakeholder,
    fetch_user,
    fetch_user_org,
    insert_user,
    link_membership,
)

_TOKEN_EXPIRY_DAYS = 7
_DT_FORMAT = "%Y-%m-%d %H:%M:%S"


def _future(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime(_DT_FORMAT)


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime(_DT_FORMAT)


def _hash_token(raw: str) -> str:
    """Fast, deterministic digest - see the module docstring for why not bcrypt."""
    return hashlib.sha256(raw.encode()).hexdigest()


async def _find_live_token(conn, raw_token: str, *, purpose: str | None = None):
    """Return the unused, unexpired row for this token, or None.

    A single indexed equality lookup (token_hash carries a UNIQUE index), not a scan - the
    property Critical 2 was about. expires_at is compared in SQL as a string, not parsed with
    strptime in Python: _DT_FORMAT sorts lexicographically the same as chronologically, and a
    malformed value here (arguably shouldn't be able to occur, but nothing that has ever
    written this column runs its output through validation) must not raise inside a request
    handler and 500 every acceptance for every other row. Note the direction this fails in: a
    garbage string such as "not-a-date" sorts *above* any real timestamp, so a malformed row
    reads as still-live rather than as expired - fails open on its own single row rather than
    failing closed (raising) for every row. Only _future() ever writes this column, so a
    malformed value should not occur in practice; the trade only matters if something else
    ever does.
    """
    sql = "SELECT * FROM auth_tokens WHERE token_hash=? AND used_at IS NULL AND expires_at > ?"
    params = [_hash_token(raw_token), _now_str()]
    if purpose is not None:
        sql += " AND purpose=?"
        params.append(purpose)
    cur = await conn.execute(sql, params)
    row = await cur.fetchone()
    return dict(row) if row else None


async def _stakeholder_matches_invite(project_slug: str, stakeholder_id: int, email: str) -> bool:
    """Whether stakeholder_id names a row on project_slug's own database AND that row's own
    email matches the one this token was issued to.

    Existence is not identity: stakeholder ids restart at 1 in every project file, so an id
    that resolves to *some* stakeholder is the ordinary case, not the exceptional one. The
    email comparison is what actually ties the invite to the person it names rather than to
    whichever record happens to occupy that integer.

    Mirrors the get_db_path(...).exists() guard in authority_service.caller_roles: a slug
    with no database yet has no stakeholders either way, and this must not create one as a
    side effect of validating a token.
    """
    if not get_db_path(project_slug).exists():
        return False
    async with get_connection(project_slug) as conn:
        project = await fetch_project(conn, slug=project_slug)
        if project is None:
            return False
        stakeholder = await fetch_stakeholder(
            conn, stakeholder_id=stakeholder_id, project_id=project["id"]
        )
        if stakeholder is None:
            return False
        return stakeholder["email"].strip().lower() == email.strip().lower()


async def issue_invite(email: str, project_slug: str, stakeholder_id: int) -> str:
    """Issue (or refresh) the one live invite for this (email, project_slug). Returns the raw
    token."""
    raw = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw)
    expires_at = _future(_TOKEN_EXPIRY_DAYS)
    async with get_system_connection() as conn:
        cur = await conn.execute(
            "SELECT id FROM auth_tokens WHERE email=? AND project_slug=? AND purpose='invite'"
            " AND used_at IS NULL",
            (email, project_slug),
        )
        row = await cur.fetchone()
        if row is None:
            await conn.execute(
                "INSERT INTO auth_tokens"
                " (token_hash, email, project_slug, stakeholder_id, purpose, expires_at)"
                " VALUES (?,?,?,?,'invite',?)",
                (token_hash, email, project_slug, stakeholder_id, expires_at),
            )
        else:
            await conn.execute(
                "UPDATE auth_tokens SET token_hash=?, stakeholder_id=?, expires_at=? WHERE id=?",
                (token_hash, stakeholder_id, expires_at, row["id"]),
            )
        await conn.commit()
    return raw


async def reissue_invite(email: str, project_slug: str | None = None) -> str | None:
    """Mint a new token onto the live invite row for this email, refreshing hash and expiry.

    Invites are now kept live per (email, project_slug), so a bare email can be ambiguous
    once somebody holds more than one outstanding invite. project_slug disambiguates when
    given; without it, this only proceeds when exactly one live invite matches - it will not
    guess which one to refresh. Returns None when there is nothing (or nothing unambiguous)
    to refresh. The superseded raw value cannot be recovered - its hash is overwritten - so
    the old link stops working.

    Note for whatever calls this without a project_slug: None conflates "nothing to refresh"
    with "ambiguous - more than one live invite, which project?" Nothing outside this file's
    own tests calls reissue_invite yet, so this is a recorded gap rather than a live one; a
    caller that needs to tell the two apart should pass project_slug, or this should grow a
    distinct return for the ambiguous case before anything does.
    """
    raw = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw)
    expires_at = _future(_TOKEN_EXPIRY_DAYS)
    async with get_system_connection() as conn:
        sql = "SELECT id FROM auth_tokens WHERE email=? AND purpose='invite' AND used_at IS NULL"
        params = [email]
        if project_slug is not None:
            sql += " AND project_slug=?"
            params.append(project_slug)
        cur = await conn.execute(sql, params)
        rows = await cur.fetchall()
        if len(rows) != 1:
            return None
        await conn.execute(
            "UPDATE auth_tokens SET token_hash=?, expires_at=? WHERE id=?",
            (token_hash, expires_at, rows[0]["id"]),
        )
        await conn.commit()
    return raw


async def accept_token(
    raw_token: str, password: str, *, purpose: str | None = None
) -> tuple[dict, bool] | None:
    """Redeem an invite or reset token: create or update the login, link if invited.

    Returns `(user, issue_session)` on success, `None` on refusal.

    Refuses (returns None):
    - a token that does not resolve to a live, unused, unexpired row (also what makes a
      token single-use - accept_token never treats used_at as a hint to ignore, the refusal
      is the enforcement);
    - a token carrying the wrong purpose, when the caller names one (the router passes
      purpose="invite" for /auth/accept and purpose="reset" for /auth/reset, so one cannot
      be redeemed as the other; direct callers, including this module's own tests, may omit
      it and accept either);
    - an invite whose stakeholder_id does not resolve, on its own project, to a stakeholder
      whose email matches the one the token was issued to. This refusal covers the whole
      acceptance - no login is created or updated, and the token is left live rather than
      stamped used - specifically so a corrected invite can still be redeemed. A refusal that
      still spent the token, or still created a login with no rights, would have no recovery
      short of hand-editing the database.

    CRITICAL, and easy to reintroduce: an invite must never change an existing account's
    password. _has_linked_login (the caller that decides whether to issue an invite at all)
    is scoped per project *by design*, so the same email legitimately gets invited onto a
    second, third, ... engagement while already holding a login from the first one. Redeeming
    that second invite must only create the new project_memberships row - not touch
    hashed_pw. Only a reset-purpose token - which the account owner triggers themselves, to
    their own address, via /auth/reset-request - may ever set a password on an account that
    already exists.

    `issue_session` closes the escalation that survives the password fix on its own: even
    with hashed_pw left untouched, a caller who blindly turned every successful acceptance
    into a session would hand the *redeemer* a live JWT as the *victim* - sub, role, and all
    - the moment an invite named an email that already had a login, silently, since the
    password was never touched and the victim has no reason to notice. Accepting an invite
    for a known email is a membership grant, not an authentication event; only the account
    owner, using their real password, may authenticate as themselves. `issue_session` is True
    exactly when this call either created a brand-new users row or redeemed a reset-purpose
    token (row["purpose"], the token's own stored purpose - not the purpose= filter a caller
    passed in, so this still holds when a direct caller omits it); the router
    (api/routers/invites.py) must not mint a session when it is False.
    """
    async with get_system_connection() as conn:
        row = await _find_live_token(conn, raw_token, purpose=purpose)
        if row is None:
            return None

        if row["project_slug"] and row["stakeholder_id"] is not None:
            if not await _stakeholder_matches_invite(
                row["project_slug"], row["stakeholder_id"], row["email"]
            ):
                return None

        user = await fetch_user(conn, username=row["email"])
        newly_created = user is None
        if user is None:
            # role="reviewer" is load-bearing, not a placeholder: check_project_access only
            # attempts the project_memberships lookup for role=="reviewer" - any other value
            # denies every project-scoped request outright regardless of membership.
            ok = await insert_user(
                conn,
                username=row["email"],
                email=row["email"],
                role="reviewer",
                hashed_pw=hash_password(password),
            )
            if not ok:
                return None
        elif row["purpose"] == "reset":
            # The one case an existing account's password may change here: a reset, which
            # only the account owner can have started (they had to receive it at their own
            # address). row["purpose"] is the *token's own* stored purpose, not the caller's
            # requested filter, so this still holds for a direct call that passed no filter.
            await conn.execute(
                "UPDATE users SET hashed_pw=? WHERE id=?", (hash_password(password), user["id"])
            )
            await conn.commit()
        # else: purpose == "invite" and the account already exists - only the membership
        # below is new. The password stays whatever it already was; they already have a
        # login and should use it, not the one just typed into this form.
        user = await fetch_user(conn, username=row["email"])

        if row["project_slug"] and row["stakeholder_id"] is not None:
            await link_membership(
                conn,
                user_id=user["id"],
                project_slug=row["project_slug"],
                stakeholder_id=row["stakeholder_id"],
            )

        await conn.execute(
            "UPDATE auth_tokens SET used_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],)
        )
        await conn.commit()
    issue_session = newly_created or row["purpose"] == "reset"
    return user, issue_session


async def issue_reset(email: str) -> str | None:
    """Issue a reset token for an existing login. Returns None for an unknown address.

    None rather than a raised error, so the /auth/reset-request endpoint cannot use the
    response to tell known addresses from unknown ones. That property has to hold under
    timing too, not just under the return value: the SELECT/INSERT-or-UPDATE run
    unconditionally, for a known and an unknown address alike, so the two cost the same up to
    the point of persisting. Only the persistence differs - a known address commits, an
    unknown one rolls back the same statement it just ran, so both do identical work but only
    one leaves a row behind. An unauthenticated caller could otherwise spray addresses and
    grow this table forever for free, which is a real incident someone reproduced: 200
    sprayed addresses left 203 rows before this. Discarding via rollback rather than skipping
    the INSERT outright is what keeps the timing flat instead of trading one oracle (existence
    by response) for another (existence by row count over time, or by the write itself being
    measurably cheaper to skip than to do).
    """
    raw = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw)
    expires_at = _future(_TOKEN_EXPIRY_DAYS)
    async with get_system_connection() as conn:
        user = await fetch_user(conn, username=email)

        cur = await conn.execute(
            "SELECT id FROM auth_tokens WHERE email=? AND purpose='reset' AND used_at IS NULL",
            (email,),
        )
        row = await cur.fetchone()
        if row is None:
            await conn.execute(
                "INSERT INTO auth_tokens (token_hash, email, purpose, expires_at)"
                " VALUES (?,?,'reset',?)",
                (token_hash, email, expires_at),
            )
        else:
            await conn.execute(
                "UPDATE auth_tokens SET token_hash=?, expires_at=? WHERE id=?",
                (token_hash, expires_at, row["id"]),
            )

        if user is None:
            await conn.rollback()
            return None
        await conn.commit()
    return raw


async def org_id_for_session(user: dict) -> int | None:
    """org_id to embed in a session token, matching /auth/login's issuance exactly.

    Without this an org_admin who resets or accepts gets a session that reads org_id as None,
    which check_project_access takes as "no org" - 403 on every project until they log out
    and back in.
    """
    if user["role"] != "org_admin":
        return None
    async with get_system_connection() as conn:
        org_row = await fetch_user_org(conn, user_id=user["id"])
    return org_row["org_id"] if org_row else None
