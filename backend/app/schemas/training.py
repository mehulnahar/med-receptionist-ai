"""Pydantic schemas for the call recording training pipeline."""

from datetime import datetime
from typing import Optional, Any
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Training Session
# ---------------------------------------------------------------------------

class TrainingSessionCreate(BaseModel):
    name: Optional[str] = Field(None, max_length=200, description="Session name (e.g. 'Initial Training')")


class TrainingSessionResponse(BaseModel):
    id: UUID
    name: Optional[str] = None
    status: str
    total_recordings: int
    processed_count: int
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TrainingSessionDetail(TrainingSessionResponse):
    """Extended session response with insights and generated prompt."""
    aggregated_insights: Optional[dict[str, Any]] = None
    generated_prompt: Optional[str] = None
    current_prompt_snapshot: Optional[str] = None
    recordings: list["TrainingRecordingResponse"] = []


class TrainingSessionListResponse(BaseModel):
    sessions: list[TrainingSessionResponse]
    total: int


# ---------------------------------------------------------------------------
# Training Recording
# ---------------------------------------------------------------------------

class TrainingRecordingResponse(BaseModel):
    id: UUID
    original_filename: str
    file_size_bytes: Optional[int] = None
    mime_type: Optional[str] = None
    status: str
    language_detected: Optional[str] = None
    duration_seconds: Optional[float] = None
    analysis: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TrainingRecordingListResponse(BaseModel):
    recordings: list[TrainingRecordingResponse]
    total: int


# ---------------------------------------------------------------------------
# Insights & Prompt
# ---------------------------------------------------------------------------

class TrainingInsightsResponse(BaseModel):
    session_id: UUID
    status: str
    total_recordings: int
    processed_count: int
    insights: Optional[dict[str, Any]] = None


class GeneratedPromptResponse(BaseModel):
    session_id: UUID
    generated_prompt: Optional[str] = None
    current_prompt: Optional[str] = None


class ApplyPromptRequest(BaseModel):
    """Optional overrides when applying the generated prompt."""
    prompt_override: Optional[str] = Field(None, description="Manual edits to the prompt before applying")
    push_to_vapi: bool = Field(True, description="Also push the prompt to Vapi assistant")
