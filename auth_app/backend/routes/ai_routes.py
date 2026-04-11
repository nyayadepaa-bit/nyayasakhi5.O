"""AI query endpoint with background processing and activity logging."""

import time
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db, async_session
from models import User, UserActivity, AIQuery
from schemas import AIQueryRequest, AIQueryResponse, MessageResponse, ChatLogRequest
from middleware.deps import get_current_user
from utils.rate_limiter import limiter
from utils.cache import cache_get, cache_set

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/ai", tags=["AI"])


async def _process_ai_query(query_id: int, input_text: str):
    """Background task: simulate/process AI query and update DB.

    In production, replace the sleep with actual LLM inference call.
    """
    start = time.perf_counter()
    try:
        # ── Simulate AI processing (replace with real inference) ──────
        await asyncio.sleep(1.5)
        response_text = (
            f"[AI Response] Based on analysis of your query regarding: "
            f"'{input_text[:100]}...', here is the legal analysis: "
            f"This matter falls under the provisions of applicable law. "
            f"Please consult a qualified legal professional for advice."
        )
        tokens_used = len(input_text.split()) * 3  # rough estimation
        latency_ms = (time.perf_counter() - start) * 1000

        async with async_session() as db:
            result = await db.execute(select(AIQuery).where(AIQuery.id == query_id))
            query = result.scalar_one_or_none()
            if query:
                query.response_text = response_text
                query.tokens_used = tokens_used
                query.latency_ms = latency_ms
                query.status = "completed"
                await db.commit()
                logger.info(f"AI query {query_id} completed in {latency_ms:.0f}ms")
    except Exception as exc:
        logger.error(f"AI query {query_id} failed: {exc}")
        async with async_session() as db:
            result = await db.execute(select(AIQuery).where(AIQuery.id == query_id))
            query = result.scalar_one_or_none()
            if query:
                query.status = "failed"
                query.response_text = f"Error: {str(exc)}"
                query.latency_ms = (time.perf_counter() - start) * 1000
                await db.commit()


@router.post("/log-chat", response_model=AIQueryResponse, status_code=201)
async def log_chat(
    body: ChatLogRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Log a chatbot query+response from the frontend (no background processing)."""
    import time
    ip = request.client.host if request.client else None

    ai_query = AIQuery(
        user_id=user.id,
        input_text=body.input_text,
        response_text=body.response_text or None,
        tokens_used=len(body.input_text.split()) + len((body.response_text or '').split()),
        latency_ms=0,
        status="completed",
    )
    db.add(ai_query)
    await db.flush()

    activity = UserActivity(
        user_id=user.id,
        input_text=body.input_text[:500],
        action_type="chatbot_query",
        ip_address=ip,
    )
    db.add(activity)
    await db.flush()

    return AIQueryResponse.model_validate(ai_query)


@router.post("/query", response_model=AIQueryResponse, status_code=202)
@limiter.limit(settings.RATE_AI_QUERY)
async def submit_ai_query(
    body: AIQueryRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit an AI query. Returns immediately with status=pending.

    The actual processing happens in the background.
    Results can be polled via GET /ai/query/{id}.
    """
    ip = request.client.host if request.client else None

    # Create AI query record
    ai_query = AIQuery(
        user_id=user.id,
        input_text=body.input_text,
        status="pending",
    )
    db.add(ai_query)
    await db.flush()

    # Log to UserActivity
    activity = UserActivity(
        user_id=user.id,
        input_text=body.input_text,
        action_type="ai_query",
        ip_address=ip,
    )
    db.add(activity)
    await db.flush()

    query_id = ai_query.id

    # Kick off background processing
    background_tasks.add_task(_process_ai_query, query_id, body.input_text)

    return AIQueryResponse.model_validate(ai_query)


@router.get("/query/{query_id}", response_model=AIQueryResponse)
async def get_ai_query(
    query_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Poll the status/result of an AI query."""
    # Check cache first
    cache_key = f"ai_query:{query_id}"
    cached = await cache_get(cache_key)
    if cached and cached.get("status") == "completed":
        return cached

    result = await db.execute(
        select(AIQuery).where(AIQuery.id == query_id, AIQuery.user_id == user.id)
    )
    query = result.scalar_one_or_none()
    if not query:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Query not found")

    resp = AIQueryResponse.model_validate(query)

    # Cache completed queries
    if query.status == "completed":
        await cache_set(cache_key, resp.model_dump(), ttl=300)

    return resp


@router.get("/queries", response_model=list[AIQueryResponse])
async def list_my_queries(
    skip: int = 0,
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's AI query history."""
    result = await db.execute(
        select(AIQuery)
        .where(AIQuery.user_id == user.id)
        .order_by(AIQuery.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return [AIQueryResponse.model_validate(q) for q in result.scalars().all()]
