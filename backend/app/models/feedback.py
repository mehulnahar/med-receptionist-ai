"""
Models for the self-improving feedback loop system.

CallFeedback  — per-call quality score + improvement signals
PromptVersion — version-controlled prompt history with performance metrics
FeedbackInsight — aggregated patterns detected across multiple calls
"""

import uuid

from sqlalchemy import (
    Column, String, Integer, Text, DateTime, Float, Boolean,
    ForeignKey, text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from app.database import Base


class CallFeedback(Base):
    """Per-call quality analysis and improvement signals."""
    __tablename__ = "call_feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    call_id = Column(UUID(as_uuid=True), ForeignKey("calls.id"), nullable=False, unique=True)
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), nullable=False)

    # Quality scores (0.0 - 1.0)
    overall_score = Column(Float, nullable=True)
    resolution_score = Column(Float, nullable=True)  # Did we resolve the caller's need?
    efficiency_score = Column(Float, nullable=True)  # How quickly?
    empathy_score = Column(Float, nullable=True)  # Was the AI warm and helpful?
    accuracy_score = Column(Float, nullable=True)  # Were tool calls correct?

    # Failure analysis
    failure_point = Column(String(100), nullable=True)  # Where did it fail? (e.g., "dob_collection", "booking")
    failure_reason = Column(Text, nullable=True)  # Why? (e.g., "caller confused by date format request")
    improvement_suggestion = Column(Text, nullable=True)  # What to change in the prompt

    # Classification
    call_complexity = Column(String(20), nullable=True)  # simple/moderate/complex
    language_detected = Column(String(10), nullable=True)  # en/es
    was_successful = Column(Boolean, nullable=True)
    caller_dropped = Column(Boolean, default=False)

    # Raw LLM analysis output
    raw_analysis = Column(JSONB, nullable=True)

    # Prompt version that was active during this call
    prompt_version = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PromptVersion(Base):
    """Version-controlled prompt history with performance tracking."""
    __tablename__ = "prompt_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    prompt_text = Column(Text, nullable=False)
    change_reason = Column(Text, nullable=True)  # Why was this version created?
    change_diff = Column(Text, nullable=True)  # What changed from previous version?

    # Performance metrics (updated as calls come in)
    total_calls = Column(Integer, default=0)
    successful_calls = Column(Integer, default=0)
    avg_score = Column(Float, nullable=True)
    avg_duration_seconds = Column(Float, nullable=True)
    booking_rate = Column(Float, nullable=True)  # % of calls that result in booking

    is_active = Column(Boolean, default=False)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    deactivated_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FeedbackInsight(Base):
    """Aggregated patterns detected across multiple calls."""
    __tablename__ = "feedback_insights"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), nullable=False)

    # Pattern classification
    insight_type = Column(String(50), nullable=False)  # failure_pattern, improvement_opportunity, language_issue, etc.
    category = Column(String(50), nullable=True)  # booking, scheduling, greeting, transfer, spanish, etc.
    severity = Column(String(20), nullable=True)  # low/medium/high/critical

    # Pattern details
    title = Column(String(255), nullable=False)  # Human-readable summary
    description = Column(Text, nullable=False)  # Detailed description
    suggested_fix = Column(Text, nullable=True)  # Proposed prompt change
    affected_calls = Column(Integer, default=0)  # How many calls showed this pattern
    sample_call_ids = Column(JSONB, nullable=True)  # Example call IDs

    # Status
    status = Column(String(20), default="open")  # open, applied, dismissed
    applied_at = Column(DateTime(timezone=True), nullable=True)
    applied_to_version = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
