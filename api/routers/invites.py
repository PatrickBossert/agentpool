# api/routers/invites.py
"""Invite acceptance and password reset - unauthenticated by design.

Somebody accepting an invite, or resetting a forgotten password, has no session yet, so all
three endpoints here sit outside require_any_auth. reset-request always answers 204, whether
or not the address has a login, so it cannot be used to enumerate which addresses exist.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.auth import create_access_token
from api.config import get_settings
from api.services.invite_service import accept_token, issue_reset

router = APIRouter(prefix="/auth", tags=["invites"])


class AcceptRequest(BaseModel):
    token: str
    password: str


class ResetRequestBody(BaseModel):
    email: str


class ResetSubmitBody(BaseModel):
    token: str
    password: str


def _login_response(user: dict) -> dict:
    settings = get_settings()
    access_token = create_access_token(user["username"], user["role"], settings.jwt_secret)
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/accept")
async def accept(req: AcceptRequest):
    user = await accept_token(req.token, req.password)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    return _login_response(user)


@router.post("/reset-request", status_code=204)
async def reset_request(req: ResetRequestBody):
    # Awaited but its result is deliberately not inspected - a 204 either way is the point.
    await issue_reset(email=req.email)


@router.post("/reset")
async def reset(req: ResetSubmitBody):
    user = await accept_token(req.token, req.password)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    return _login_response(user)
