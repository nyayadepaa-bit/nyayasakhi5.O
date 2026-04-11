"""User routes: profile, submit input, view own activity."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import User, UserActivity
from schemas import UserPublic, UserUpdate, UserInputRequest, MessageResponse, ActivityView
from middleware.deps import get_current_user

router = APIRouter(prefix="/user", tags=["User"])


@router.get("/me", response_model=UserPublic)
async def get_profile(user: User = Depends(get_current_user)):
    return UserPublic.model_validate(user)


@router.patch("/me", response_model=UserPublic)
async def update_profile(
    body: UserUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.name is not None:
        user.name = body.name
    return UserPublic.model_validate(user)


@router.post("/input", response_model=MessageResponse, status_code=201)
async def submit_input(
    body: UserInputRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Log a user input (chat query, etc.) into the database."""
    ip = request.client.host if request.client else None
    activity = UserActivity(
        user_id=user.id,
        input_text=body.input_text,
        action_type=body.action_type,
        ip_address=ip,
    )
    db.add(activity)
    return {"message": "Input recorded"}


@router.get("/activity", response_model=list[ActivityView])
async def get_my_activity(
    skip: int = 0,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """View the current user's own activity history."""
    result = await db.execute(
        select(UserActivity)
        .where(UserActivity.user_id == user.id)
        .order_by(UserActivity.timestamp.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = result.scalars().all()
    return [
        ActivityView(
            id=r.id,
            user_id=r.user_id,
            user_name=user.name,
            user_email=user.email,
            input_text=r.input_text,
            action_type=r.action_type,
            timestamp=r.timestamp,
            ip_address=r.ip_address,
        )
        for r in rows
    ]
