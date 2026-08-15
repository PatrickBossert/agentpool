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
    though `exp` keeps moving forward. That is what lets the middleware enforce
    ABSOLUTE_SESSION_EXPIRE_DAYS as a ceiling the rolling expiry can approach but never
    outlive - without a preserved iat, every roll would look like a session started right
    now, and the absolute cap would never bind.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload: dict = {"sub": username, "role": role, "exp": expire, "iat": iat or now}
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


def require_org_admin_or_above(payload: dict = Depends(get_token_payload)) -> dict:
    if payload.get("role") not in ("sysadmin", "org_admin"):
        raise HTTPException(status_code=403, detail="Org admin or above required")
    return payload


def require_any_auth(payload: dict = Depends(get_token_payload)) -> dict:
    """Any valid token — just verifies authentication."""
    return payload


# ── Project-level access check ────────────────────────────────────────────────

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
