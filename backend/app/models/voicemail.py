"""Voicemail message model."""
import uuid
from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, ForeignKey, CheckConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Voicemail(Base):
    __tablename__ = "voicemails"
    __table_args__ = (
        CheckConstraint(
            "status IN ('new', 'read', 'responded', 'archived')",
            name="ck_voicemails_status",
        ),
        CheckConstraint(
            "urgency IN ('normal', 'urgent', 'emergency')",
            name="ck_voicemails_urgency",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), nullable=False)
    call_id = Column(UUID(as_uuid=True), ForeignKey("calls.id", ondelete="SET NULL"), nullable=True)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="SET NULL"), nullable=True)

    # Caller info
    caller_name = Column(String(255), nullable=True)
    caller_phone = Column(String(20), nullable=True)

    # Message content
    message = Column(Text, nullable=False)
    urgency = Column(String(20), default="normal")  # normal, urgent, emergency
    callback_requested = Column(Boolean, default=True)
    preferred_callback_time = Column(String(100), nullable=True)  # e.g. "morning", "after 2pm"
    reason = Column(String(100), nullable=True)  # appointment, refill, billing, question, other

    # Status
    status = Column(String(20), default="new")  # new, read, responded, archived
    responded_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    responded_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    practice = relationship("Practice", lazy="select")
    patient = relationship("Patient", lazy="selectin")
