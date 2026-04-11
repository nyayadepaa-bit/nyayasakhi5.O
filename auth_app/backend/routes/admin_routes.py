"""Admin routes: user management, activity logs, analytics, audit log, conversations, export."""

import io
import json
import time
from datetime import datetime, timedelta, timezone, date
from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, or_, cast, Date, extract, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from models import User, UserActivity, AIQuery, AdminAction
from schemas import (
    AdminUserView, ActivityView, AnalyticsResponse,
    AdminToggleRequest, MessageResponse, UserPublic,
    AdminActionView, PaginatedActivityResponse, DailyCount,
    UserConversation, ConversationMessage, PaginatedConversationResponse,
    EnhancedAnalyticsResponse, CategoryCount,
)
from middleware.deps import require_admin
from utils.cache import cache_get, cache_set, cache_delete

settings = get_settings()
router = APIRouter(prefix="/admin", tags=["Admin"])

# Track startup time for uptime calculation
_startup_time = time.time()

def _format_uptime(seconds: float) -> str:
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    mins = int((seconds % 3600) // 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{mins}m")
    return " ".join(parts)


async def _log_admin_action(
    db: AsyncSession,
    admin: User,
    action: str,
    target_user_id: UUID | None = None,
    details: str | None = None,
    ip_address: str | None = None,
) -> None:
    """Insert an audit record into admin_actions."""
    entry = AdminAction(
        admin_id=admin.id,
        action=action,
        target_user_id=target_user_id,
        details=details,
        ip_address=ip_address,
    )
    db.add(entry)
    await db.flush()


# ── Analytics ─────────────────────────────────────────

@router.get("/analytics", response_model=AnalyticsResponse)
async def analytics(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    # Try cache first
    cached = await cache_get("admin:analytics")
    if cached:
        return cached

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    active_users = (await db.execute(
        select(func.count(User.id)).where(User.is_active == True)
    )).scalar() or 0
    admin_count = (await db.execute(
        select(func.count(User.id)).where(User.role == "admin")
    )).scalar() or 0
    total_inputs = (await db.execute(
        select(func.count(UserActivity.id))
    )).scalar() or 0
    users_today = (await db.execute(
        select(func.count(User.id)).where(User.created_at >= today_start)
    )).scalar() or 0
    inputs_today = (await db.execute(
        select(func.count(UserActivity.id)).where(UserActivity.timestamp >= today_start)
    )).scalar() or 0
    queries_today = (await db.execute(
        select(func.count(AIQuery.id)).where(AIQuery.created_at >= today_start)
    )).scalar() or 0

    # ── Chart data: last 30 days ──────────────────────
    thirty_days_ago = now - timedelta(days=30)

    # Users per day
    upd_result = await db.execute(
        select(
            cast(User.created_at, Date).label("day"),
            func.count(User.id),
        )
        .where(User.created_at >= thirty_days_ago)
        .group_by("day")
        .order_by("day")
    )
    users_per_day = [DailyCount(date=str(row[0]), count=row[1]) for row in upd_result.all()]

    # Queries per day (from UserActivity with ai_query type)
    qpd_result = await db.execute(
        select(
            cast(UserActivity.timestamp, Date).label("day"),
            func.count(UserActivity.id),
        )
        .where(UserActivity.timestamp >= thirty_days_ago)
        .group_by("day")
        .order_by("day")
    )
    queries_per_day = [DailyCount(date=str(row[0]), count=row[1]) for row in qpd_result.all()]

    uptime = _format_uptime(time.time() - _startup_time)

    result = AnalyticsResponse(
        total_users=total_users,
        active_users=active_users,
        total_inputs=total_inputs,
        queries_today=queries_today,
        users_today=users_today,
        inputs_today=inputs_today,
        server_uptime=uptime,
        admin_count=admin_count,
        users_per_day=users_per_day,
        queries_per_day=queries_per_day,
    )

    await cache_set("admin:analytics", result.model_dump(), ttl=settings.CACHE_TTL)
    return result


# ── List all users ────────────────────────────────────

@router.get("/users", response_model=list[AdminUserView])
async def list_users(
    search: str = Query(default="", max_length=200),
    role: str = Query(default=""),
    skip: int = 0,
    limit: int = 50,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(User.name.ilike(pattern), User.email.ilike(pattern))
        )
    if role:
        stmt = stmt.where(User.role == role)

    stmt = stmt.order_by(User.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    users = result.scalars().all()

    # Fetch activity counts
    user_ids = [u.id for u in users]
    if user_ids:
        counts_result = await db.execute(
            select(UserActivity.user_id, func.count(UserActivity.id))
            .where(UserActivity.user_id.in_(user_ids))
            .group_by(UserActivity.user_id)
        )
        counts = dict(counts_result.all())
    else:
        counts = {}

    return [
        AdminUserView(
            **UserPublic.model_validate(u).model_dump(),
            activity_count=counts.get(u.id, 0),
        )
        for u in users
    ]


# ── View user activity (with advanced filters + pagination) ───

@router.get("/activity", response_model=PaginatedActivityResponse)
async def list_activity(
    user_id: str = Query(default=""),
    search: str = Query(default="", max_length=200),
    email: str = Query(default="", max_length=200),
    action_type: str = Query(default="", max_length=50),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    base = (
        select(UserActivity, User.name, User.email)
        .join(User, UserActivity.user_id == User.id)
    )
    count_base = (
        select(func.count(UserActivity.id))
        .select_from(UserActivity)
        .join(User, UserActivity.user_id == User.id)
    )

    # Filters
    if user_id:
        base = base.where(UserActivity.user_id == UUID(user_id))
        count_base = count_base.where(UserActivity.user_id == UUID(user_id))
    if email:
        pattern = f"%{email}%"
        base = base.where(User.email.ilike(pattern))
        count_base = count_base.where(User.email.ilike(pattern))
    if search:
        pattern = f"%{search}%"
        cond = or_(
            UserActivity.input_text.ilike(pattern),
            User.name.ilike(pattern),
            User.email.ilike(pattern),
        )
        base = base.where(cond)
        count_base = count_base.where(cond)
    if action_type:
        base = base.where(UserActivity.action_type == action_type)
        count_base = count_base.where(UserActivity.action_type == action_type)
    if date_from:
        try:
            dt = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            base = base.where(UserActivity.timestamp >= dt)
            count_base = count_base.where(UserActivity.timestamp >= dt)
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
            base = base.where(UserActivity.timestamp < dt)
            count_base = count_base.where(UserActivity.timestamp < dt)
        except ValueError:
            pass

    total = (await db.execute(count_base)).scalar() or 0
    offset = (page - 1) * page_size
    pages = max(1, (total + page_size - 1) // page_size)

    stmt = base.order_by(UserActivity.timestamp.desc()).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    rows = result.all()

    items = [
        ActivityView(
            id=act.id,
            user_id=act.user_id,
            user_name=name,
            user_email=uemail,
            input_text=act.input_text,
            action_type=act.action_type,
            timestamp=act.timestamp,
            ip_address=act.ip_address,
        )
        for act, name, uemail in rows
    ]

    return PaginatedActivityResponse(
        items=items, total=total, page=page, page_size=page_size, pages=pages
    )


# ── Toggle user active/disabled ──────────────────────

@router.patch("/users/{user_id}/toggle", response_model=MessageResponse)
async def toggle_user(
    user_id: UUID,
    body: AdminToggleRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.role == "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot disable admin accounts")

    user.is_active = body.is_active
    action = "enabled" if body.is_active else "disabled"

    ip = request.client.host if request.client else None
    await _log_admin_action(
        db, admin, f"user_{action}",
        target_user_id=user_id,
        details=f"User {user.email} was {action}",
        ip_address=ip,
    )
    await cache_delete("admin:analytics")

    return {"message": f"User {user.email} has been {action}"}


# ── Delete user ───────────────────────────────────────

@router.delete("/users/{user_id}", response_model=MessageResponse)
async def delete_user(
    user_id: UUID,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.role == "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete admin accounts")

    name = user.name
    email = user.email
    city = user.city or "N/A"
    ip = request.client.host if request.client else None
    await _log_admin_action(
        db, admin, "user_deleted",
        target_user_id=user_id,
        details=f"Deleted: {name} ({email}) city={city}",
        ip_address=ip,
    )

    await db.delete(user)
    await cache_delete("admin:analytics")
    return {"message": f"User {name} ({email}) deleted"}


# ── Bulk delete users ─────────────────────────────────

@router.post("/users/bulk-delete", response_model=MessageResponse)
async def bulk_delete_users(
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple non-admin users at once."""
    body = await request.json()
    user_ids = body.get("user_ids", [])
    if not user_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No user IDs provided")

    ip = request.client.host if request.client else None
    deleted = 0
    for uid_str in user_ids:
        uid = UUID(uid_str)
        result = await db.execute(select(User).where(User.id == uid))
        user = result.scalar_one_or_none()
        if not user or user.role == "admin":
            continue
        name = user.name
        email = user.email
        city = user.city or "N/A"
        await _log_admin_action(
            db, admin, "user_deleted",
            target_user_id=uid,
            details=f"Bulk deleted: {name} ({email}) city={city}",
            ip_address=ip,
        )
        await db.delete(user)
        deleted += 1

    await cache_delete("admin:analytics")
    return {"message": f"{deleted} user(s) deleted"}


# ── Bulk delete conversations ─────────────────────────

@router.post("/conversations/bulk-delete", response_model=MessageResponse)
async def bulk_delete_conversations(
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete all conversation records for the specified users."""
    body = await request.json()
    user_ids = body.get("user_ids", [])
    if not user_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No user IDs provided")

    ip = request.client.host if request.client else None
    deleted = 0
    activity_deleted = 0
    for uid_str in user_ids:
        uid = UUID(uid_str)
        cnt = (await db.execute(
            select(func.count(AIQuery.id)).where(AIQuery.user_id == uid)
        )).scalar() or 0
        if cnt == 0:
            continue
        await db.execute(sa_delete(AIQuery).where(AIQuery.user_id == uid))
        deleted += cnt

        # Also delete associated UserActivity records so the data
        # disappears from the entire dashboard (analytics, activity, etc.)
        act_cnt = (await db.execute(
            select(func.count(UserActivity.id)).where(UserActivity.user_id == uid)
        )).scalar() or 0
        if act_cnt > 0:
            await db.execute(sa_delete(UserActivity).where(UserActivity.user_id == uid))
            activity_deleted += act_cnt

        user_result = await db.execute(select(User).where(User.id == uid))
        user = user_result.scalar_one_or_none()
        name = user.name if user else "Unknown"
        email = user.email if user else uid_str
        await _log_admin_action(
            db, admin, "conversations_deleted",
            target_user_id=uid,
            details=f"Deleted {cnt} conversations and {act_cnt} activity records for: {name} ({email})",
            ip_address=ip,
        )

    return {"message": f"{deleted} conversation(s) and {activity_deleted} activity record(s) deleted"}


# ── Admin Audit Log ───────────────────────────────────

@router.get("/audit-log", response_model=list[AdminActionView])
async def get_audit_log(
    skip: int = 0,
    limit: int = 50,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return admin action audit trail."""
    stmt = (
        select(
            AdminAction,
            User.email.label("admin_email"),
        )
        .outerjoin(User, AdminAction.admin_id == User.id)
        .order_by(AdminAction.timestamp.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()

    # For target_email, do a second lookup (batch)
    target_ids = [r[0].target_user_id for r in rows if r[0].target_user_id]
    target_emails = {}
    if target_ids:
        tresult = await db.execute(
            select(User.id, User.email).where(User.id.in_(target_ids))
        )
        target_emails = dict(tresult.all())

    import re as _re

    def _resolve_target(action):
        """Return target email from DB lookup, or extract from details if user was deleted."""
        email = target_emails.get(action.target_user_id)
        if email:
            return email
        # Deleted user — extract name/email from details string
        if action.details:
            m = _re.search(r":\s*(.+?)$", action.details.split("\n")[0])
            if m:
                return m.group(1).strip()
        return None

    return [
        AdminActionView(
            id=action.id,
            admin_id=action.admin_id,
            admin_email=admin_email,
            action=action.action,
            target_user_id=action.target_user_id,
            target_email=_resolve_target(action),
            details=action.details,
            timestamp=action.timestamp,
            ip_address=action.ip_address,
        )
        for action, admin_email in rows
    ]


# ── Conversations (grouped by user) ──────────────────

@router.get("/conversations", response_model=PaginatedConversationResponse)
async def list_conversations(
    search: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List users with their AI conversation messages (grouped by user)."""
    # Count users with AI queries
    count_base = (
        select(func.count(func.distinct(AIQuery.user_id)))
        .select_from(AIQuery)
        .join(User, AIQuery.user_id == User.id)
    )
    base = (
        select(
            User.id, User.name, User.email, User.city,
            func.count(AIQuery.id).label("msg_count"),
            func.max(AIQuery.created_at).label("last_active"),
        )
        .join(AIQuery, AIQuery.user_id == User.id)
        .group_by(User.id, User.name, User.email, User.city)
    )
    if search:
        pattern = f"%{search}%"
        cond = or_(User.name.ilike(pattern), User.email.ilike(pattern))
        base = base.where(cond)
        count_base = count_base.where(cond)

    total = (await db.execute(count_base)).scalar() or 0
    pages = max(1, (total + page_size - 1) // page_size)
    offset = (page - 1) * page_size

    stmt = base.order_by(func.max(AIQuery.created_at).desc()).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    rows = result.all()

    items = []
    for uid, name, email, city, msg_count, last_act in rows:
        items.append(UserConversation(
            user_id=uid,
            user_name=name,
            user_email=email,
            city=city,
            message_count=msg_count,
            last_active=last_act,
            messages=[],  # messages fetched separately via drill-down
        ))

    return PaginatedConversationResponse(
        items=items, total=total, page=page, page_size=page_size, pages=pages
    )


@router.get("/conversations/{user_id}", response_model=list[ConversationMessage])
async def get_user_conversations(
    user_id: UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get all AI conversation messages for a specific user."""
    result = await db.execute(
        select(AIQuery)
        .where(AIQuery.user_id == user_id)
        .order_by(AIQuery.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    queries = result.scalars().all()
    return [
        ConversationMessage(
            id=q.id,
            input_text=q.input_text,
            response_text=q.response_text,
            timestamp=q.created_at,
        )
        for q in queries
    ]


# ── Enhanced Analytics ────────────────────────────────

@router.get("/analytics/enhanced", response_model=EnhancedAnalyticsResponse)
async def enhanced_analytics(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Extended analytics with breakdowns for charts."""
    cached = await cache_get("admin:enhanced_analytics")
    if cached:
        return cached

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    thirty_days_ago = now - timedelta(days=30)

    # Base counts
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    active_users = (await db.execute(
        select(func.count(User.id)).where(User.is_active == True)
    )).scalar() or 0
    admin_count = (await db.execute(
        select(func.count(User.id)).where(User.role == "admin")
    )).scalar() or 0
    total_inputs = (await db.execute(select(func.count(UserActivity.id)))).scalar() or 0
    queries_today = (await db.execute(
        select(func.count(AIQuery.id)).where(AIQuery.created_at >= today_start)
    )).scalar() or 0
    users_today = (await db.execute(
        select(func.count(User.id)).where(User.created_at >= today_start)
    )).scalar() or 0
    inputs_today = (await db.execute(
        select(func.count(UserActivity.id)).where(UserActivity.timestamp >= today_start)
    )).scalar() or 0

    uptime = _format_uptime(time.time() - _startup_time)

    # Users per day (30d)
    upd_result = await db.execute(
        select(cast(User.created_at, Date).label("day"), func.count(User.id))
        .where(User.created_at >= thirty_days_ago)
        .group_by("day").order_by("day")
    )
    users_per_day = [DailyCount(date=str(r[0]), count=r[1]) for r in upd_result.all()]

    # Queries per day (30d)
    qpd_result = await db.execute(
        select(cast(UserActivity.timestamp, Date).label("day"), func.count(UserActivity.id))
        .where(UserActivity.timestamp >= thirty_days_ago)
        .group_by("day").order_by("day")
    )
    queries_per_day = [DailyCount(date=str(r[0]), count=r[1]) for r in qpd_result.all()]

    # Active users per day (users who had activity, 30d)
    aupd_result = await db.execute(
        select(
            cast(UserActivity.timestamp, Date).label("day"),
            func.count(func.distinct(UserActivity.user_id)),
        )
        .where(UserActivity.timestamp >= thirty_days_ago)
        .group_by("day").order_by("day")
    )
    active_users_per_day = [DailyCount(date=str(r[0]), count=r[1]) for r in aupd_result.all()]

    # Avg queries per user
    total_querying_users = (await db.execute(
        select(func.count(func.distinct(AIQuery.user_id)))
    )).scalar() or 1
    total_ai_queries = (await db.execute(select(func.count(AIQuery.id)))).scalar() or 0
    avg_queries_per_user = round(total_ai_queries / max(total_querying_users, 1), 2)

    # Top action types
    at_result = await db.execute(
        select(UserActivity.action_type, func.count(UserActivity.id))
        .group_by(UserActivity.action_type)
        .order_by(func.count(UserActivity.id).desc())
        .limit(10)
    )
    top_action_types = [CategoryCount(name=r[0], count=r[1]) for r in at_result.all()]

    # Users by city
    uc_result = await db.execute(
        select(User.city, func.count(User.id))
        .where(User.city.isnot(None))
        .group_by(User.city)
        .order_by(func.count(User.id).desc())
        .limit(15)
    )
    users_by_city = [CategoryCount(name=r[0] or "Unknown", count=r[1]) for r in uc_result.all()]

    # Users by role
    ur_result = await db.execute(
        select(User.role, func.count(User.id))
        .group_by(User.role)
    )
    users_by_role = [CategoryCount(name=r[0], count=r[1]) for r in ur_result.all()]

    # Hourly activity distribution (last 30d)
    ha_result = await db.execute(
        select(
            extract("hour", UserActivity.timestamp).label("hr"),
            func.count(UserActivity.id),
        )
        .where(UserActivity.timestamp >= thirty_days_ago)
        .group_by("hr").order_by("hr")
    )
    hourly_activity = [CategoryCount(name=f"{int(r[0]):02d}:00", count=r[1]) for r in ha_result.all()]

    # AI query status breakdown
    qs_result = await db.execute(
        select(AIQuery.status, func.count(AIQuery.id))
        .group_by(AIQuery.status)
    )
    ai_query_status_breakdown = [CategoryCount(name=r[0], count=r[1]) for r in qs_result.all()]

    result = EnhancedAnalyticsResponse(
        total_users=total_users, active_users=active_users, total_inputs=total_inputs,
        queries_today=queries_today, users_today=users_today, inputs_today=inputs_today,
        server_uptime=uptime, admin_count=admin_count,
        users_per_day=users_per_day, queries_per_day=queries_per_day,
        queries_per_day_line=queries_per_day,
        active_users_per_day=active_users_per_day,
        avg_queries_per_user=avg_queries_per_user,
        top_action_types=top_action_types,
        users_by_city=users_by_city,
        users_by_role=users_by_role,
        hourly_activity=hourly_activity,
        ai_query_status_breakdown=ai_query_status_breakdown,
    )

    await cache_set("admin:enhanced_analytics", result.model_dump(), ttl=settings.CACHE_TTL)
    return result


# ── Data Export (conversation-centric) ────────────────

@router.get("/export")
async def export_data(
    format: str = Query(default="json", regex="^(json|txt)$"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Export full conversations grouped by user with all variables."""
    # Fetch all users who have AI queries
    users_result = await db.execute(
        select(User).order_by(User.created_at.desc())
    )
    all_users = users_result.scalars().all()
    user_map = {u.id: u for u in all_users}

    # Fetch ALL AI queries with full data
    queries_result = await db.execute(
        select(AIQuery).order_by(AIQuery.created_at.asc())
    )
    all_queries = queries_result.scalars().all()

    # Group conversations by user
    from collections import defaultdict
    convos_by_user = defaultdict(list)
    for q in all_queries:
        convos_by_user[q.user_id].append(q)

    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%Y%m%d_%H%M%S")

    # Build conversation-centric export
    conversations = []
    for uid, queries in convos_by_user.items():
        u = user_map.get(uid)
        user_info = {
            "user_id": str(uid),
            "name": u.name if u else "[Deleted User]",
            "email": u.email if u else None,
            "age": u.age if u else None,
            "city": u.city if u else None,
            "role": u.role if u else "user",
            "is_active": u.is_active if u else False,
            "joined": u.created_at.isoformat() if u and u.created_at else None,
            "last_login": u.last_login.isoformat() if u and u.last_login else None,
        }
        messages = []
        for q in queries:
            messages.append({
                "id": q.id,
                "user_query": q.input_text,
                "ai_response": q.response_text,
                "tokens_used": q.tokens_used,
                "latency_ms": q.latency_ms,
                "status": q.status,
                "timestamp": q.created_at.isoformat() if q.created_at else None,
            })
        conversations.append({
            **user_info,
            "total_messages": len(messages),
            "conversation": messages,
        })

    # Sort by total messages descending
    conversations.sort(key=lambda c: c["total_messages"], reverse=True)

    export_payload = {
        "report": "NyayaDepaaAI — Conversation Export",
        "generated_at": now_utc.isoformat(),
        "total_users_with_conversations": len(conversations),
        "total_messages": sum(c["total_messages"] for c in conversations),
        "conversations": conversations,
    }

    if format == "json":
        content = json.dumps(export_payload, indent=2, ensure_ascii=False)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=nyayadepaaai_export_{now_str}.json"},
        )
    else:  # txt
        W = 72
        lines = []
        lines.append("=" * W)
        lines.append("  NYAYADEPAAAI — CONVERSATION EXPORT")
        lines.append("=" * W)
        lines.append(f"  Generated : {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append(f"  Users     : {len(conversations)}")
        lines.append(f"  Messages  : {sum(c['total_messages'] for c in conversations)}")
        lines.append("=" * W)
        lines.append("")

        for idx, c in enumerate(conversations, 1):
            lines.append("-" * W)
            lines.append(f"  USER #{idx}")
            lines.append(f"  Name    : {c['name']}")
            lines.append(f"  Email   : {c['email'] or 'N/A'}")
            lines.append(f"  Age     : {c['age'] or 'N/A'}")
            lines.append(f"  City    : {c['city'] or 'N/A'}")
            lines.append(f"  Role    : {c['role']}")
            lines.append(f"  Active  : {c['is_active']}")
            lines.append(f"  Joined  : {c['joined'] or 'N/A'}")
            lines.append(f"  Messages: {c['total_messages']}")
            lines.append("-" * W)

            for mi, m in enumerate(c["conversation"], 1):
                lines.append(f"")
                lines.append(f"  [{mi}] {m['timestamp'] or ''}")
                lines.append(f"      STATUS  : {m['status']}")
                lines.append(f"      TOKENS  : {m['tokens_used'] or 0}")
                lines.append(f"      LATENCY : {m['latency_ms'] or 0:.0f} ms")
                lines.append(f"      USER  >>  {m['user_query']}")
                lines.append(f"      AI    >>  {m['ai_response'] or '[No response]'}")

            lines.append("")

        lines.append("=" * W)
        lines.append("  END OF REPORT")
        lines.append("=" * W)

        content = "\n".join(lines)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename=nyayadepaaai_export_{now_str}.txt"},
        )


@router.get("/export/meta")
async def export_meta(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Quick data count check for smart download feature."""
    total_users_with_convos = (await db.execute(
        select(func.count(func.distinct(AIQuery.user_id)))
    )).scalar() or 0
    total_queries = (await db.execute(select(func.count(AIQuery.id)))).scalar() or 0
    latest_query = (await db.execute(
        select(func.max(AIQuery.created_at))
    )).scalar()
    return {
        "total_records": total_queries,
        "total_users_with_convos": total_users_with_convos,
        "total_messages": total_queries,
        "latest_timestamp": (latest_query or datetime.min.replace(tzinfo=timezone.utc)).isoformat(),
    }


# ── Per-user export ──────────────────────────────────

@router.get("/export/user/{user_id}")
async def export_user_data(
    user_id: UUID,
    format: str = Query(default="json", regex="^(json|txt)$"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Export conversations for a single user."""
    user_result = await db.execute(select(User).where(User.id == user_id))
    u = user_result.scalar_one_or_none()

    queries_result = await db.execute(
        select(AIQuery).where(AIQuery.user_id == user_id).order_by(AIQuery.created_at.asc())
    )
    all_queries = queries_result.scalars().all()

    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%Y%m%d_%H%M%S")
    user_name = u.name if u else "deleted_user"
    safe_name = user_name.replace(" ", "_").lower()

    user_info = {
        "user_id": str(user_id),
        "name": u.name if u else "[Deleted User]",
        "email": u.email if u else None,
        "age": u.age if u else None,
        "city": u.city if u else None,
        "role": u.role if u else "user",
        "is_active": u.is_active if u else False,
        "joined": u.created_at.isoformat() if u and u.created_at else None,
        "last_login": u.last_login.isoformat() if u and u.last_login else None,
    }

    messages = []
    for q in all_queries:
        messages.append({
            "id": q.id,
            "user_query": q.input_text,
            "ai_response": q.response_text,
            "tokens_used": q.tokens_used,
            "latency_ms": q.latency_ms,
            "status": q.status,
            "timestamp": q.created_at.isoformat() if q.created_at else None,
        })

    export_payload = {
        "report": f"NyayaDepaaAI — User Export: {user_info['name']}",
        "generated_at": now_utc.isoformat(),
        "total_messages": len(messages),
        **user_info,
        "conversation": messages,
    }

    if format == "json":
        content = json.dumps(export_payload, indent=2, ensure_ascii=False)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=nyayadepaaai_{safe_name}_{now_str}.json"},
        )
    else:
        W = 72
        lines = []
        lines.append("=" * W)
        lines.append(f"  NYAYADEPAAAI — USER EXPORT: {user_info['name'].upper()}")
        lines.append("=" * W)
        lines.append(f"  Generated : {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append(f"  Name      : {user_info['name']}")
        lines.append(f"  Email     : {user_info['email'] or 'N/A'}")
        lines.append(f"  Age       : {user_info['age'] or 'N/A'}")
        lines.append(f"  City      : {user_info['city'] or 'N/A'}")
        lines.append(f"  Role      : {user_info['role']}")
        lines.append(f"  Active    : {user_info['is_active']}")
        lines.append(f"  Joined    : {user_info['joined'] or 'N/A'}")
        lines.append(f"  Messages  : {len(messages)}")
        lines.append("=" * W)
        lines.append("")

        for mi, m in enumerate(messages, 1):
            lines.append(f"  [{mi}] {m['timestamp'] or ''}")
            lines.append(f"      STATUS  : {m['status']}")
            lines.append(f"      TOKENS  : {m['tokens_used'] or 0}")
            lines.append(f"      LATENCY : {m['latency_ms'] or 0:.0f} ms")
            lines.append(f"      USER  >>  {m['user_query']}")
            lines.append(f"      AI    >>  {m['ai_response'] or '[No response]'}")
            lines.append("")

        lines.append("=" * W)
        lines.append("  END OF REPORT")
        lines.append("=" * W)

        content = "\n".join(lines)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename=nyayadepaaai_{safe_name}_{now_str}.txt"},
        )
