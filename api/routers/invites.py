# api/routers/invites.py
"""Invite acceptance and password reset - unauthenticated by design.

Somebody accepting an invite, or resetting a forgotten password, has no session yet, so all
three endpoints here sit outside require_any_auth. reset-request always answers 204, whether
or not the address has a login, so it cannot be used to enumerate which addresses exist -
issue_reset does the same DB work either way so the answer cannot be told apart by timing
either.

/auth/accept and /auth/reset both redeem through accept_token, but each pins the purpose it
will accept: an invite token cannot be redeemed as a reset or vice versa, even though the
underlying function does not enforce that on its own (direct callers, including tests, may
still redeem either purpose - see invite_service.accept_token's docstring).

CRITICAL: /auth/accept must not mint a session when the invite named an email that already
had a login. accept_token leaves that account's password untouched (see its own docstring),
but a session minted anyway would still hand the *redeemer* of the token a live JWT as the
*victim* - sub, role, and all - with nothing to notice, since the password never changed.
Accepting an invite for a known email is a membership grant, not an authentication event: the
person already holds credentials and must sign in with them. accept_token's second return
value, issue_session, is exactly this signal - True only when the call created a brand-new
login or redeemed a reset (which only the account owner can have requested, to their own
address). See _accept_response below for the no-session shape.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.auth import create_access_token
from api.config import get_settings
from api.services.invite_service import accept_token, issue_reset, org_id_for_session

router = APIRouter(prefix="/auth", tags=["invites"])


class AcceptRequest(BaseModel):
    token: str
    password: str


class ResetRequestBody(BaseModel):
    email: str


class ResetSubmitBody(BaseModel):
    token: str
    password: str


async def _login_response(user: dict) -> dict:
    settings = get_settings()
    org_id = await org_id_for_session(user)
    access_token = create_access_token(
        user["username"], user["role"], settings.jwt_secret, org_id=org_id
    )
    return {"access_token": access_token, "token_type": "bearer"}


def _already_registered_response() -> dict:
    """The membership was granted, but no session - see the module docstring's CRITICAL
    note. `access_token: None` rather than omitting the key, so a client that only checks
    truthiness (as AcceptInvite.tsx does) and one that only checks for the key's presence
    both land on the same "no session" answer.

    `detail` is the single place this outcome is worded. AcceptInvite.tsx renders it
    verbatim, so the sentence a person reads cannot drift from the one the API promises.
    It has to say what was discarded, not only what was granted: whoever redeemed this
    token typed a password twice on the way here, and the previous wording ("sign in with
    your existing password") read to at least one person as the password they had just
    chosen. They then found only the old one worked and had no idea why."""
    return {
        "access_token": None,
        "token_type": "bearer",
        "already_registered": True,
        "detail": "An account already exists for this email address, so this invite "
                  "granted your access only. The password you just entered was not set - "
                  "your existing password still works, and it is the one to sign in with.",
    }


@router.post("/accept")
async def accept(req: AcceptRequest):
    result = await accept_token(req.token, req.password, purpose="invite")
    if result is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    user, issue_session = result
    if not issue_session:
        return _already_registered_response()
    return await _login_response(user)


@router.post("/reset-request", status_code=204)
async def reset_request(req: ResetRequestBody):
    # Awaited but its result is deliberately not inspected - a 204 either way is the point.
    await issue_reset(email=req.email)


@router.post("/reset")
async def reset(req: ResetSubmitBody):
    result = await accept_token(req.token, req.password, purpose="reset")
    if result is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    user, _issue_session = result
    # accept_token guarantees issue_session is True whenever row["purpose"] == "reset" - see
    # its own docstring - and purpose="reset" here pins the redeemed row to exactly that
    # purpose, so this path always reaches a real login response.
    return await _login_response(user)
