"""Pydantic request / response schemas."""

from datetime import datetime, date
from uuid import UUID
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field


# ── Auth ──────────────────────────────────────────────

class GuestLoginRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    age: int = Field(..., ge=1, le=150)
    city: str = Field(..., min_length=2, max_length=120)


class SignupRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "UserPublic"


class RefreshRequest(BaseModel):
    refresh_token: str


class MessageResponse(BaseModel):
    message: str


# ── User ──────────────────────────────────────────────

class UserPublic(BaseModel):
    id: UUID
    name: str
    age: Optional[int] = None
    city: Optional[str] = None
    email: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    name: Optional[str] = None


class UserInputRequest(BaseModel):
    input_text: str = Field(..., min_length=1, max_length=5000)
    action_type: str = Field(default="chat_query", max_length=50)


# ── AI Query ─────────────────────────────────────────

class AIQueryRequest(BaseModel):
    input_text: str = Field(..., min_length=1, max_length=10000)


class ChatLogRequest(BaseModel):
    input_text: str = Field(..., min_length=1, max_length=10000)
    response_text: str = Field(default='', max_length=50000)


class ChatStartRequest(BaseModel):
    session_id: str = Field(..., min_length=2, max_length=120)
    message: str = Field(..., min_length=1, max_length=10000)


class ChatStartResponse(BaseModel):
    summary: str
    confirmation_needed: bool = True


class ChatConfirmRequest(BaseModel):
    session_id: str = Field(..., min_length=2, max_length=120)
    confirmed: bool
    correction: Optional[str] = Field(default=None, max_length=6000)


class ChatConfirmResponse(BaseModel):
    followup_questions: List[str]


class ChatFollowupRequest(BaseModel):
    session_id: str = Field(..., min_length=2, max_length=120)
    answers: dict[str, str]


class ChatFollowupResponse(BaseModel):
    status: str
    ready_for_analysis: bool


class ChatFinalizeRequest(BaseModel):
    session_id: str = Field(..., min_length=2, max_length=120)


class ChatFinalizeResponse(BaseModel):
    final_response: dict[str, str]


class AIQueryResponse(BaseModel):
    id: int
    input_text: str
    response_text: Optional[str] = None
    tokens_used: Optional[int] = 0
    latency_ms: Optional[float] = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Admin ─────────────────────────────────────────────

class AdminUserView(UserPublic):
    activity_count: int = 0


class ActivityView(BaseModel):
    id: int
    user_id: UUID
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    input_text: str
    action_type: str
    timestamp: datetime
    ip_address: Optional[str] = None

    model_config = {"from_attributes": True}


class DailyCount(BaseModel):
    date: str
    count: int


class AnalyticsResponse(BaseModel):
    total_users: int
    active_users: int
    total_inputs: int
    queries_today: int
    users_today: int
    inputs_today: int
    server_uptime: str
    admin_count: int
    users_per_day: List[DailyCount] = []
    queries_per_day: List[DailyCount] = []


class AdminToggleRequest(BaseModel):
    is_active: bool


class AdminActionView(BaseModel):
    id: int
    admin_id: Optional[UUID] = None
    admin_email: Optional[str] = None
    action: str
    target_user_id: Optional[UUID] = None
    target_email: Optional[str] = None
    details: Optional[str] = None
    timestamp: datetime
    ip_address: Optional[str] = None


class PaginatedActivityResponse(BaseModel):
    items: List[ActivityView]
    total: int
    page: int
    page_size: int
    pages: int


# ── Conversation views ────────────────────────────────

class ConversationMessage(BaseModel):
    id: int
    input_text: str
    response_text: Optional[str] = None
    timestamp: datetime

    model_config = {"from_attributes": True}


class UserConversation(BaseModel):
    user_id: UUID
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    city: Optional[str] = None
    message_count: int = 0
    last_active: Optional[datetime] = None
    messages: List[ConversationMessage] = []


class PaginatedConversationResponse(BaseModel):
    items: List[UserConversation]
    total: int
    page: int
    page_size: int
    pages: int


# ── Enhanced Analytics ────────────────────────────────

class CategoryCount(BaseModel):
    name: str
    count: int


class EnhancedAnalyticsResponse(AnalyticsResponse):
    """Extended analytics with dialog flow breakdowns."""
    queries_per_day_line: List[DailyCount] = []
    active_users_per_day: List[DailyCount] = []
    avg_queries_per_user: float = 0.0
    top_action_types: List[CategoryCount] = []
    users_by_city: List[CategoryCount] = []
    users_by_role: List[CategoryCount] = []
    hourly_activity: List[CategoryCount] = []
    ai_query_status_breakdown: List[CategoryCount] = []


# ── Export ────────────────────────────────────────────

class ExportMeta(BaseModel):
    format: str
    record_count: int
    generated_at: datetime


class ErrorResponse(BaseModel):
    status: str = "error"
    message: str


# Rebuild forward refs
TokenResponse.model_rebuild()
