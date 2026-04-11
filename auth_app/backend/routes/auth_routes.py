"""Auth routes: guest-login (name+age), admin-login, refresh."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from models import User
from schemas import (
    GuestLoginRequest, LoginRequest, TokenResponse,
    RefreshRequest, MessageResponse, UserPublic,
)
from utils.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    decode_token,
)
from utils.rate_limiter import limiter

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["Auth"])


# ── Guest Login (name + age → JWT) ───────────────────

@router.post("/guest-login", response_model=TokenResponse, status_code=200)
@limiter.limit(settings.RATE_SIGNUP)
async def guest_login(body: GuestLoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Create a guest user with just name + age and return a JWT."""
    user = User(
        name=body.name,
        age=body.age,
        city=body.city,
        role="user",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    user.last_login = datetime.now(timezone.utc)

    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id),
        user=UserPublic.model_validate(user),
    )


# ── Admin login ───────────────────────────────────────

@router.post("/admin/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LOGIN)
async def admin_login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(User.email == body.email, User.role == "admin")
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid admin credentials")

    user.last_login = datetime.now(timezone.utc)

    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id),
        user=UserPublic.model_validate(user),
    )


# ── Refresh token ─────────────────────────────────────

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found or disabled")

    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id),
        user=UserPublic.model_validate(user),
    )
