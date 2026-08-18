# api/auth.py
from datetime import datetime, timedelta, timezone
import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

ALGORITHM = "HS256"
# Thirty days, rolled forward on every authenticated request (see api/main.py's
# roll_session middleware) - so an active reviewer never sees the login page twice.
ACCESS_TOKEN_EXPIRE_HOURS = 24 * 30
# The roll above has no ceiling of its own - a token used once a month would refresh
# forever. This is the belt to the middleware's user-existence-check braces: a session
# started this long ago must re-authenticate even if the rolling exp would otherwise still
# be comfortably in the future and the account still exists in good standing.
ABSOLUTE_SESSION_EXPIRE_DAYS = 90

_bearer = HTTPBearer()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(
    username: str, role: str, secret: str, *, org_id: int | None = None,
    iat: datetime | None = None,
) -> str:
    """Mint a session token.

    `iat` defaults to now - the moment a login, accept, or reset issues a brand new session.
    api/main.py's roll_session middleware passes the *original* iat back in on every reissue
    instead of taking that default, so a session's issued-at time survives every roll even
    though `exp` keeps moving forward. That is what lets ABSOLUTE_SESSION_EXPIRE_DAYS act as
    a ceiling the rolling expiry can approach but never outlive - without a preserved iat,
    every roll would look like a session started right now, and the absolute cap would never
    bind.

    `exp` itself is clamped to `iat + ABSOLUTE_SESSION_EXPIRE_DAYS` when that is sooner than
    the ordinary thirty-day rolling window - not only "future rolls get refused past the
    cap" (roll_session's own age check) but "no single roll can mint an exp that reaches
    past it" in the first place. Without the clamp, a roll on day eighty-nine would still
    hand out a full thirty-day exp landing on day one-nineteen, and decode_token has no
    other check that would catch a session outliving the cap - it only rejects an *expired*
    token, and iat is not itself an expiry claim. For a brand-new session (iat defaults to
    now) the clamp never binds, since now + 90 days is always later than now + 30 days.
    """
    now = datetime.now(timezone.utc)
    effective_iat = iat or now
    expire = min(
        now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
        effective_iat + timedelta(days=ABSOLUTE_SESSION_EXPIRE_DAYS),
    )
    payload: dict = {"sub": username, "role": role, "exp": expire, "iat": effective_iat}
    if org_id is not None:
        payload["org_id"] = org_id
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_token(token: str, secret: str) -> dict:
    try:
        return jwt.decode(token, secret, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_token_payload(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> dict:
    """FastAPI dependency — extracts and validates the Bearer token."""
    from api.config import get_settings
    return decode_token(credentials.credentials, get_settings().jwt_secret)


# ── Role-based dependencies ───────────────────────────────────────────────────

def require_sysadmin(payload: dict = Depends(get_token_payload)) -> dict:
    if payload.get("role") != "sysadmin":
        raise HTTPException(status_code=403, detail="Sysadmin role required")
    return payload


def is_org_admin_or_above(payload: dict) -> bool:
    """The platform tier, as a question rather than a refusal.

    `require_org_admin_or_above` is a FastAPI dependency, so a caller that merely wants to
    *report* whether this door would open - GET /my-permissions, which the stakeholder list
    asks before offering the invite-link action - cannot use it without catching its own
    403. The rule is stated here once and asserted from both sides in
    tests/test_grantable_roles.py: an answer that drifted from the door would put a button
    in front of somebody it refuses, which is worse than no button.
    """
    return (payload or {}).get("role") in ("sysadmin", "org_admin")


def require_org_admin_or_above(payload: dict = Depends(get_token_payload)) -> dict:
    if not is_org_admin_or_above(payload):
        raise HTTPException(status_code=403, detail="Org admin or above required")
    return payload


def require_any_auth(payload: dict = Depends(get_token_payload)) -> dict:
    """Any valid token — just verifies authentication."""
    return payload


# ── Project-level access check ────────────────────────────────────────────────

def may_access_org(org_id: int, payload: dict) -> bool:
    """The rule `check_org_access` refuses with, as a question rather than a refusal.

    Same split as `is_org_admin_or_above` / `require_org_admin_or_above` above, and for the
    same reason: a caller that needs the *answer* rather than a 403 - the knowledge tiers'
    organisation-boundary check, which asks it about a destination store rather than a path
    segment - cannot use a function whose only output is an exception it would have to
    catch. Stated once, so the two cannot drift; the reasoning is in `check_org_access`.
    """
    role = (payload or {}).get("role")
    if role == "sysadmin":
        return True
    return role == "org_admin" and (payload or {}).get("org_id") == org_id


def check_org_access(org_id: int, payload: dict) -> None:
    """Raises 403 if the caller may not administer this organisation.

    The counterpart to check_project_access for doors whose path names an *organisation*
    rather than a slug. Synchronous, because the answer is entirely in the JWT: an org_admin's
    org_id is embedded at login (see org_id_for_session), so there is nothing to look up.

    Why it exists, and why it is not merely tidiness. `_assert_may_administer` in
    admin_service decides whether an account belongs to the caller's organisation by reading
    `org_memberships` - and `POST` and `DELETE /auth/orgs/{org_id}/members` are the doors that
    *write that table*. Both took org_id from the path and compared it to nothing, so an
    org_admin refused on another organisation's account could delete its membership, add it to
    their own organisation, and come back: the guard asks "is this account in my organisation?"
    and the caller could simply make the answer yes. Three requests at the same tier, ending in
    a password of their choosing on somebody else's account.

    A gate that reads a table is worth nothing if a caller can write themselves into it - the
    same sentence CLAUDE.md already carries about `project_memberships`, on the table one layer
    up. sysadmin returns early, so administering across organisations stays a sysadmin
    capability.
    """
    if not may_access_org(org_id, payload):
        raise HTTPException(status_code=403, detail="Access denied to this organisation")


async def check_project_access(slug: str, payload: dict) -> None:
    """Raises 403 if the calling user has no access to this project slug.

    Opens its own system DB connection — call this inside endpoint handlers,
    not as a FastAPI dependency (it needs the slug at call time).
    """
    role = payload.get("role")
    if role == "sysadmin":
        return

    from api.database import (
        get_system_connection, fetch_user, fetch_project_registry,
        has_project_membership,
    )

    async with get_system_connection() as conn:
        if role == "org_admin":
            org_id = payload.get("org_id")
            row = await fetch_project_registry(conn, slug=slug)
            if row and row["org_id"] == org_id:
                return
        elif role == "reviewer":
            user = await fetch_user(conn, username=payload["sub"])
            if user and await has_project_membership(conn, user_id=user["id"], project_slug=slug):
                return

    raise HTTPException(status_code=403, detail="Access denied to this project")
