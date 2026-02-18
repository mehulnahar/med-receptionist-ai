"""Pydantic schemas for Call endpoints."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CallResponse(BaseModel):
    """Single call record returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    vapi_call_id: str | None = None
    direction: str
    caller_number: str | None = None  # mapped from Call.caller_phone
    caller_name: str | None = None  # saved early by save_caller_info tool
    status: str | None = None
    duration_seconds: int | None = None
    patient_id: UUID | None = None
    patient_name: str | None = None  # joined from Patient
    started_at: datetime | None = None
    ended_at: datetime | None = None
    transcript: str | None = None  # mapped from Call.transcription
    summary: str | None = None  # mapped from Call.ai_summary
    cost: Decimal | None = None  # mapped from Call.vapi_cost
    recording_url: str | None = None
    created_at: datetime
    ended_reason: str | None = None  # mapped from Call.outcome
    callback_needed: bool = False
    callback_completed: bool = False
    callback_notes: str | None = None
    callback_completed_at: datetime | None = None
    structured_data: dict | None = None  # Vapi structured analysis
    caller_intent: str | None = None  # From structured data
    caller_sentiment: str | None = None  # From structured data
    success_evaluation: str | None = None  # Vapi success eval
    language: str | None = None  # Detected language (en/es)


class CallListResponse(BaseModel):
    """Paginated list of calls."""

    calls: list[CallResponse]
    total: int


class CallbackUpdateRequest(BaseModel):
    """Request to update callback status on a call."""
    callback_completed: bool | None = None
    callback_notes: str | None = None


class CallbackListResponse(BaseModel):
    """Response for callback list endpoint."""
    callbacks: list[CallResponse]
    total: int


class CallStatsResponse(BaseModel):
    """Dashboard call statistics."""
    total_calls_today: int = 0
    missed_calls_today: int = 0
    avg_duration_seconds: int = 0
    callbacks_pending: int = 0
    total_calls_week: int = 0
    total_cost_today: float = 0.0
