# api/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from api.auth import (
    create_access_token,
    get_token_payload,
    hash_password,
    verify_password,
    require_sysadmin,
)
from api.config import get_settings
from api.database import fetch_user, insert_user, get_system_connection, fetch_user_org

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends()):
    settings = get_settings()

    # Built-in env-var admin always gets sysadmin role
    if form.username == settings.admin_username:
        if form.password != settings.admin_password:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_access_token(form.username, "sysadmin", settings.jwt_secret)
        return TokenResponse(access_token=token)

    # System DB users
    async with get_system_connection() as conn:
        user = await fetch_user(conn, username=form.username)
        if not user or not verify_password(form.password, user["hashed_pw"]):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        # Embed org_id for org_admin tokens
        org_id: int | None = None
        if user["role"] == "org_admin":
            org_row = await fetch_user_org(conn, user_id=user["id"])
            if org_row:
                org_id = org_row["org_id"]
        token = create_access_token(
            user["username"], user["role"], settings.jwt_secret, org_id=org_id
        )
    return TokenResponse(access_token=token)
