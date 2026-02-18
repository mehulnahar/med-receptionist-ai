"""
AppointmentReminder model for the outbound reminder system.

Tracks scheduled SMS (and future voice) reminders for appointments,
including delivery status, patient responses, and retry attempts.
"""

import uuid

from sqlalchemy import (
    Column, String, Integer, Text, DateTime, ForeignKey, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class AppointmentReminder(Base):
    __tablename__ = "appointment_reminders"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id"), nullable=False)
    appointment_id = Column(UUID(as_uuid=True), ForeignKey("appointments.id"), nullable=False)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)

    # "sms", "call", or "both"
    reminder_type = Column(String(20), nullable=False, default="sms")

    # When this reminder should be sent
    scheduled_for = Column(DateTime(timezone=True), nullable=False)

    # When it was actually sent (NULL until sent)
    sent_at = Column(DateTime(timezone=True), nullable=True)

    # pending, sent, failed, cancelled
    status = Column(String(20), nullable=False, default="pending")

    # The rendered SMS body (stored at schedule time for auditability)
    message_content = Column(Text, nullable=True)

    # Patient's reply text (CONFIRM, CANCEL, RESCHEDULE, or free-form)
    response = Column(Text, nullable=True)

    # Twilio message SID for tracking delivery
    message_sid = Column(String(100), nullable=True)

    # Number of send attempts (for retry logic)
    attempts = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    practice = relationship("Practice", lazy="selectin")
    appointment = relationship("Appointment", lazy="selectin")
    patient = relationship("Patient", lazy="selectin")

    def __repr__(self):
        return (
            f"<AppointmentReminder(id={self.id}, type='{self.reminder_type}', "
            f"status='{self.status}', scheduled_for={self.scheduled_for})>"
        )
