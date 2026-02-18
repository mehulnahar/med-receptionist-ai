"""Prescription refill request model."""
import uuid
from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class RefillRequest(Base):
    __tablename__ = "refill_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id"), nullable=False)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=True)
    call_id = Column(UUID(as_uuid=True), ForeignKey("calls.id"), nullable=True)

    # Prescription details
    medication_name = Column(String(255), nullable=False)
    dosage = Column(String(100), nullable=True)
    pharmacy_name = Column(String(255), nullable=True)
    pharmacy_phone = Column(String(20), nullable=True)
    prescribing_doctor = Column(String(255), nullable=True)

    # Caller info
    caller_name = Column(String(255), nullable=True)
    caller_phone = Column(String(20), nullable=True)

    # Request info
    urgency = Column(String(20), default="normal")  # normal, urgent, emergency
    notes = Column(Text, nullable=True)

    # Status tracking
    status = Column(String(30), default="pending")  # pending, in_review, approved, denied, completed
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    practice = relationship("Practice", lazy="selectin")
    patient = relationship("Patient", lazy="selectin")
