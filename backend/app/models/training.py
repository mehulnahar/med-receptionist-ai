"""
Models for the call recording training pipeline.

TrainingSession  — a batch of uploaded recordings for analysis
TrainingRecording — an individual uploaded recording with transcript + analysis
"""

import uuid

from sqlalchemy import (
    Column, String, Integer, Text, DateTime, Float, Boolean,
    ForeignKey, text, Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class TrainingSession(Base):
    """A batch of uploaded call recordings for analysis and prompt calibration."""
    __tablename__ = "training_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(200), nullable=True)  # e.g. "Initial Training - Feb 2026"

    # Processing status
    status = Column(String(20), default="pending", nullable=False)  # pending, processing, completed, failed

    # Counts
    total_recordings = Column(Integer, default=0, nullable=False)
    processed_count = Column(Integer, default=0, nullable=False)

    # Results (populated after all recordings processed)
    aggregated_insights = Column(JSONB, nullable=True)  # Combined analysis across all recordings
    generated_prompt = Column(Text, nullable=True)  # AI-suggested system prompt
    current_prompt_snapshot = Column(Text, nullable=True)  # Prompt at time of generation (for diff)

    # Audit
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    recordings = relationship("TrainingRecording", back_populates="session", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_training_sessions_practice", "practice_id"),
    )


class TrainingRecording(Base):
    """An individual call recording uploaded for training analysis."""
    __tablename__ = "training_recordings"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(UUID(as_uuid=True), ForeignKey("training_sessions.id", ondelete="CASCADE"), nullable=False)

    # File metadata (audio is NOT stored — streamed to Whisper then discarded)
    original_filename = Column(String(255), nullable=False)
    file_size_bytes = Column(Integer, nullable=True)
    mime_type = Column(String(50), nullable=True)

    # Processing status
    status = Column(String(20), default="uploaded", nullable=False)  # uploaded, transcribing, analyzing, completed, failed

    # Transcription results (from Whisper)
    transcript = Column(Text, nullable=True)
    language_detected = Column(String(10), nullable=True)  # en, es, etc.
    duration_seconds = Column(Float, nullable=True)

    # Analysis results (from GPT-4o-mini)
    analysis = Column(JSONB, nullable=True)
    # Expected structure:
    # {
    #   "caller_intent": "booking" | "cancellation" | "refill" | "billing" | "question" | "other",
    #   "language": "en" | "es",
    #   "common_phrases": ["phrase1", "phrase2"],
    #   "receptionist_approach": "description of how the receptionist handled the call",
    #   "info_collected": ["name", "dob", "insurance", ...],
    #   "call_outcome": "booked" | "transferred" | "callback" | "voicemail" | "resolved" | "unresolved",
    #   "difficulty_points": ["description of any difficulties"],
    #   "insurance_mentions": ["MetroPlus", "Fidelis"],
    #   "appointment_type_mentions": ["follow-up", "new patient"],
    #   "caller_sentiment": "positive" | "neutral" | "frustrated" | "confused",
    #   "summary": "Brief 1-2 sentence summary"
    # }

    error_message = Column(Text, nullable=True)

    # Audit
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    session = relationship("TrainingSession", back_populates="recordings")

    __table_args__ = (
        Index("ix_training_recordings_session", "session_id"),
        Index("ix_training_recordings_practice", "practice_id"),
    )
