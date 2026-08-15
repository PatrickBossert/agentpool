# api/services/invite_service.py
"""Invite, accept, and reset - how somebody gets a login.

One token table backs both purposes: an 'invite' creates the users row and the project
membership together; a 'reset' only replaces the password on a login that already exists,
which is why its token carries no project_slug or stakeholder_id.

Tokens are stored hashed with the same bcrypt hash_password/verify_password used for account
passwords - never the raw value, and never logged. Because a hash cannot be reversed, a
re-issued invite necessarily mints a brand new token onto the same row rather than resending
the original: the old link dies, which is the correct trade for a token that sets a password.

One live invite per person is enforced by refreshing the existing unused row instead of
inserting a second - two live invites would let two people each set a password against a
single stakeholder record.

accept_token is the main caller of link_membership. project_memberships.stakeholder_id lives
in system.db while the stakeholder itself lives in the project's own database, so no foreign
key can catch a mismatch - and stakeholder ids restart at 1 in every project file. A
mislinked id does not fail; it silently resolves to an unrelated person's rights. So before
linking, this module checks that the stakeholder id named on the token actually exists on the
project named on the token, and refuses to link (though the login itself is still created)
if it does not.
"""
import secrets
from datetime import datetime, timedelta, timezone

from api.auth import hash_password, verify_password
from api.database import (
    get_connection,
    get_db_path,
    get_system_connection,
    fetch_project,
    fetch_stakeholder,
    fetch_user,
    insert_user,
    link_membership,
)

_TOKEN_EXPIRY_DAYS = 7
_DT_FORMAT = "%Y-%m-%d %H:%M:%S"


def _future(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime(_DT_FORMAT)


def _is_expired(expires_at: str) -> bool:
    naive_now = datetime.now(timezone.utc).replace(tzinfo=None)
    return datetime.strptime(expires_at, _DT_FORMAT) < naive_now


async def _find_live_token(conn, raw_token: str):
    """Return the unused, unexpired row whose hash matches raw_token, or None.

    Tokens are hashed with bcrypt, which salts randomly, so the same raw value hashes to a
    different string every time - there is no deterministic digest to look up by equality.
    Every unused, unexpired row is checked with verify_password instead.
    """
    cur = await conn.execute("SELECT * FROM auth_tokens WHERE used_at IS NULL")
    async for row in cur:
        row = dict(row)
        if _is_expired(row["expires_at"]):
            continue
        if verify_password(raw_token, row["token_hash"]):
            return row
    return None


async def _stakeholder_belongs_to_project(project_slug: str, stakeholder_id: int) -> bool:
    """Whether stakeholder_id names a real row on project_slug's own database.

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
        return stakeholder is not None


async def issue_invite(email: str, project_slug: str, stakeholder_id: int) -> str:
    """Issue (or refresh) the one live invite for this email. Returns the raw token."""
    raw = secrets.token_urlsafe(32)
    token_hash = hash_password(raw)
    expires_at = _future(_TOKEN_EXPIRY_DAYS)
    async with get_system_connection() as conn:
        cur = await conn.execute(
            "SELECT id FROM auth_tokens WHERE email=? AND purpose='invite' AND used_at IS NULL",
            (email,),
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
                "UPDATE auth_tokens SET token_hash=?, project_slug=?, stakeholder_id=?,"
                " expires_at=? WHERE id=?",
                (token_hash, project_slug, stakeholder_id, expires_at, row["id"]),
            )
        await conn.commit()
    return raw


async def reissue_invite(email: str) -> str | None:
    """Mint a new token onto the live invite row for this email.

    Returns None if there is no live invite to refresh. The superseded raw value cannot be
    recovered - its hash is overwritten - so the old link stops working.
    """
    raw = secrets.token_urlsafe(32)
    token_hash = hash_password(raw)
    expires_at = _future(_TOKEN_EXPIRY_DAYS)
    async with get_system_connection() as conn:
        cur = await conn.execute(
            "SELECT id FROM auth_tokens WHERE email=? AND purpose='invite' AND used_at IS NULL",
            (email,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        await conn.execute(
            "UPDATE auth_tokens SET token_hash=?, expires_at=? WHERE id=?",
            (token_hash, expires_at, row["id"]),
        )
        await conn.commit()
    return raw


async def accept_token(raw_token: str, password: str) -> dict | None:
    """Redeem an invite or reset token: create or update the login, link if invited.

    Refuses (returns None) a token that does not resolve to a live, unused, unexpired row -
    which is what makes a token single-use: accept_token never looks at used_at as a hint to
    ignore, it is the refusal itself.
    """
    async with get_system_connection() as conn:
        row = await _find_live_token(conn, raw_token)
        if row is None:
            return None

        hashed_pw = hash_password(password)
        user = await fetch_user(conn, username=row["email"])
        if user is None:
            ok = await insert_user(
                conn,
                username=row["email"],
                email=row["email"],
                role="reviewer",
                hashed_pw=hashed_pw,
            )
            if not ok:
                return None
        else:
            await conn.execute(
                "UPDATE users SET hashed_pw=? WHERE id=?", (hashed_pw, user["id"])
            )
            await conn.commit()
        user = await fetch_user(conn, username=row["email"])

        if row["project_slug"] and row["stakeholder_id"] is not None:
            if await _stakeholder_belongs_to_project(row["project_slug"], row["stakeholder_id"]):
                await link_membership(
                    conn,
                    user_id=user["id"],
                    project_slug=row["project_slug"],
                    stakeholder_id=row["stakeholder_id"],
                )
            # else: refuse to link - the id does not name a real person on this project, so
            # linking it would silently grant whoever happens to sit at that id instead.

        await conn.execute(
            "UPDATE auth_tokens SET used_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],)
        )
        await conn.commit()
    return user


async def issue_reset(email: str) -> str | None:
    """Issue a reset token for an existing login. Returns None for an unknown address.

    None rather than a raised error, so a caller (the /auth/reset-request endpoint) cannot
    use the response to tell known addresses from unknown ones.
    """
    async with get_system_connection() as conn:
        user = await fetch_user(conn, username=email)
        if user is None:
            return None

        raw = secrets.token_urlsafe(32)
        token_hash = hash_password(raw)
        expires_at = _future(_TOKEN_EXPIRY_DAYS)
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
        await conn.commit()
    return raw
