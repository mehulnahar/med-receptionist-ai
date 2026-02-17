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


class CallListResponse(BaseModel):
    """Paginated list of calls."""

    calls: list[CallResponse]
    total: int
