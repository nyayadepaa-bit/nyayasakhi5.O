"""
Conversational legal intake chat routes.

Single unified endpoint handles the entire conversation flow:
  - Phase 1 (gathering): Natural conversational information gathering
  - Phase 2 (analysis): Structured legal case analysis output

The conversation memory is maintained server-side and treated as the
single source of truth.
"""

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from typing import Optional

from services.rag_workflow import (
    SessionState,
    store,
    process_message,
    analyze_completeness,
    _build_full_text,
)

router = APIRouter(prefix="/chat", tags=["Conversation Flow"])


# ── Request / Response Models ─────────────────────────────

class ChatMessageRequest(BaseModel):
    session_id: str = Field(..., min_length=2, max_length=120)
    message: str = Field(..., min_length=1, max_length=10000)


class ChatMessageResponse(BaseModel):
    response: str
    phase: str  # "gathering" or "analysis"
    completeness: float  # 0.0 to 1.0
    is_final: bool
    exchange_count: int
    resolved_attributes: dict[str, bool] = {}
    missing_attributes: list[str] = []
    final_response: Optional[dict[str, str]] = None


class SessionInfoResponse(BaseModel):
    session_id: str
    phase: str
    exchange_count: int
    completeness: float
    resolved_attributes: dict[str, bool]
    missing_attributes: list[str]
    message_count: int
    has_final_analysis: bool


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[dict[str, str]]
    phase: str
    completeness: float


# ── Endpoints ─────────────────────────────────────────────

@router.post("/message", response_model=ChatMessageResponse)
async def chat_message(body: ChatMessageRequest, request: Request):
    """
    Main conversational endpoint. Handles both Phase 1 (gathering) and
    Phase 2 (analysis) automatically based on conversation completeness.

    The system will:
    - In Phase 1: Ask targeted follow-up questions naturally
    - Transition to Phase 2 when completeness threshold is met or user requests analysis
    - In Phase 2: Generate the structured legal analysis
    """
    result = process_message(body.session_id, body.message)

    state = store.get(body.session_id)
    exchange_count = state.exchange_count if state else 0

    return ChatMessageResponse(
        response=result["response"],
        phase=result["phase"],
        completeness=result["completeness"],
        is_final=result["is_final"],
        exchange_count=exchange_count,
        resolved_attributes=result.get("resolved", {}),
        missing_attributes=result.get("missing", []),
        final_response=result.get("final_response"),
    )


@router.get("/session/{session_id}", response_model=SessionInfoResponse)
async def get_session_info(session_id: str):
    """Get current session state and completeness information."""
    state = store.get(session_id)
    if not state:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")

    full_text = _build_full_text(state)
    resolved, ratio, missing = analyze_completeness(full_text)

    return SessionInfoResponse(
        session_id=session_id,
        phase=state.phase,
        exchange_count=state.exchange_count,
        completeness=round(ratio, 2),
        resolved_attributes=resolved,
        missing_attributes=missing,
        message_count=len(state.messages),
        has_final_analysis=state.final_analysis is not None,
    )


@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(session_id: str):
    """Get the full conversation history for a session."""
    state = store.get(session_id)
    if not state:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")

    full_text = _build_full_text(state)
    _, ratio, _ = analyze_completeness(full_text)

    return ChatHistoryResponse(
        session_id=session_id,
        messages=state.messages,
        phase=state.phase,
        completeness=round(ratio, 2),
    )


@router.post("/reset/{session_id}")
async def reset_session(session_id: str):
    """Reset a session to start a new conversation."""
    state = store.get(session_id)
    if state:
        new_state = SessionState(session_id=session_id)
        store.set(new_state)
    return {"status": "reset", "session_id": session_id}


# ── Legacy Compatibility Endpoints ────────────────────────
# These wrap the new unified flow for backward compatibility

class LegacyChatStartRequest(BaseModel):
    session_id: str = Field(..., min_length=2, max_length=120)
    message: str = Field(..., min_length=1, max_length=10000)


class LegacyChatStartResponse(BaseModel):
    summary: str
    confirmation_needed: bool = True


class LegacyChatConfirmRequest(BaseModel):
    session_id: str = Field(..., min_length=2, max_length=120)
    confirmed: bool
    correction: Optional[str] = Field(default=None, max_length=6000)


class LegacyChatConfirmResponse(BaseModel):
    followup_questions: list[str]


class LegacyChatFollowupRequest(BaseModel):
    session_id: str = Field(..., min_length=2, max_length=120)
    answers: dict[str, str]


class LegacyChatFollowupResponse(BaseModel):
    status: str
    ready_for_analysis: bool


class LegacyChatFinalizeRequest(BaseModel):
    session_id: str = Field(..., min_length=2, max_length=120)


class LegacyChatFinalizeResponse(BaseModel):
    final_response: dict[str, str]


@router.post("/start", response_model=LegacyChatStartResponse)
async def legacy_chat_start(body: LegacyChatStartRequest, request: Request):
    """Legacy: Start a conversation (maps to the new unified flow)."""
    result = process_message(body.session_id, body.message)
    return LegacyChatStartResponse(
        summary=result["response"],
        confirmation_needed=not result["is_final"],
    )


@router.post("/confirm", response_model=LegacyChatConfirmResponse)
async def legacy_chat_confirm(body: LegacyChatConfirmRequest, request: Request):
    """Legacy: Confirm or correct the summary."""
    state = store.get(body.session_id)
    if not state:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")

    if not body.confirmed and body.correction:
        result = process_message(body.session_id, body.correction)
    else:
        result = process_message(body.session_id, "The information is correct. Please continue.")

    return LegacyChatConfirmResponse(
        followup_questions=result.get("missing", [])[:5],
    )


@router.post("/followup", response_model=LegacyChatFollowupResponse)
async def legacy_chat_followup(body: LegacyChatFollowupRequest, request: Request):
    """Legacy: Submit follow-up answers."""
    state = store.get(body.session_id)
    if not state:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")

    combined = " | ".join(f"{k}: {v}" for k, v in body.answers.items() if v.strip())
    if combined:
        process_message(body.session_id, combined)

    return LegacyChatFollowupResponse(status="facts_updated", ready_for_analysis=True)


@router.post("/finalize", response_model=LegacyChatFinalizeResponse)
async def legacy_chat_finalize(body: LegacyChatFinalizeRequest, request: Request):
    """Legacy: Finalize and generate the structured analysis."""
    result = process_message(body.session_id, "Please generate my legal analysis now.")
    final = result.get("final_response")
    if not final:
        final = {
            "Victim Case Summary": "Unable to generate analysis. Please provide more details.",
            "Predicted Legal Outcomes": "Insufficient information.",
            "Expected Duration of the Case": "Cannot estimate.",
            "Decision Recommendation": "Provide more details for a recommendation.",
            "Reason for Recommendation": "Insufficient case information.",
            "Recommended Next Actions": "Please share more details about your situation.",
        }
    return LegacyChatFinalizeResponse(final_response=final)
