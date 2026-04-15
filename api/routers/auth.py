# api/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from api.auth import (
    create_access_token,
    get_token_payload,
    hash_password,
    verify_password,
)
from api.config import get_settings
from api.database import fetch_user, insert_user, get_system_connection

router = APIRouter(prefix="/auth", tags=["auth"])


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "consultant"
    project_slug: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends()):
    settings = get_settings()
    # Check built-in admin credentials from config
    if form.username == settings.admin_username:
        if form.password != settings.admin_password:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_access_token(form.username, "consultant", settings.jwt_secret)
        return TokenResponse(access_token=token)

    # Check system DB users
    async with get_system_connection() as conn:
        user = await fetch_user(conn, username=form.username)
    if not user or not verify_password(form.password, user["hashed_pw"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(user["username"], user["role"], settings.jwt_secret)
    return TokenResponse(access_token=token)


@router.post("/users", status_code=201)
async def create_user(
    req: UserCreate,
    payload: dict = Depends(get_token_payload),
):
    if payload.get("role") != "consultant":
        raise HTTPException(status_code=403, detail="Consultant role required")
    async with get_system_connection() as conn:
        ok = await insert_user(
            conn,
            username=req.username,
            role=req.role,
            hashed_pw=hash_password(req.password),
            project_slug=req.project_slug,
        )
    if not ok:
        raise HTTPException(status_code=409, detail="Username already exists")
    return {"username": req.username, "role": req.role}
