import uuid

from sqlalchemy import Column, String, Integer, Text, DateTime, Numeric, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Call(Base):
    __tablename__ = "calls"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id"), nullable=False)
    vapi_call_id = Column(String(255), nullable=True)
    twilio_call_sid = Column(String(255), nullable=True)
    caller_phone = Column(String(20), nullable=True)
    direction = Column(String(10), default="inbound", nullable=False)
    language = Column(String(5), default="en", nullable=False)
    duration_seconds = Column(Integer, nullable=True)
    status = Column(String(30), nullable=True)
    outcome = Column(String(30), nullable=True)
    recording_url = Column(Text, nullable=True)
    transcription = Column(Text, nullable=True)
    ai_summary = Column(Text, nullable=True)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=True)
    appointment_id = Column(UUID(as_uuid=True), ForeignKey("appointments.id"), nullable=True)
    vapi_cost = Column(Numeric(10, 4), nullable=True)
    twilio_cost = Column(Numeric(10, 4), nullable=True)
    call_metadata = Column("metadata", JSON, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    practice = relationship("Practice", back_populates="calls", lazy="selectin")
    patient = relationship("Patient", back_populates="calls", lazy="selectin")
    appointment = relationship("Appointment", lazy="selectin")

    def __repr__(self):
        return f"<Call(id={self.id}, vapi_call_id='{self.vapi_call_id}', status='{self.status}')>"
