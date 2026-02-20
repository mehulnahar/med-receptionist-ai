import uuid

from sqlalchemy import Column, String, Integer, Text, Date, Time, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), nullable=False)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=True)
    patient_name = Column(String(255), nullable=False)
    patient_phone = Column(String(20), nullable=False)
    appointment_type_id = Column(UUID(as_uuid=True), ForeignKey("appointment_types.id"), nullable=True)
    preferred_date_start = Column(Date, nullable=True)
    preferred_date_end = Column(Date, nullable=True)
    preferred_time_start = Column(Time, nullable=True)
    preferred_time_end = Column(Time, nullable=True)
    notes = Column(Text, nullable=True)
    priority = Column(Integer, default=3, nullable=False)  # 1 (highest) to 5 (lowest)
    status = Column(String(20), default="waiting", nullable=False)  # waiting, notified, booked, expired, cancelled
    notified_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    practice = relationship("Practice", lazy="select")
    patient = relationship("Patient", lazy="selectin")
    appointment_type = relationship("AppointmentType", lazy="selectin")

    def __repr__(self):
        return f"<WaitlistEntry(id={self.id}, patient='{self.patient_name}', status='{self.status}')>"
