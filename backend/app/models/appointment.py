import uuid

from sqlalchemy import Column, Index, String, Integer, Boolean, Text, Date, Time, DateTime, ForeignKey, CheckConstraint, text
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        Index("ix_appointments_availability", "practice_id", "date", "time", "status"),
        Index("ix_appointments_patient", "practice_id", "patient_id"),
        CheckConstraint(
            "status IN ('booked', 'confirmed', 'entered_in_ehr', 'cancelled', 'no_show', 'completed')",
            name="ck_appointments_status",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), nullable=False)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    appointment_type_id = Column(UUID(as_uuid=True), ForeignKey("appointment_types.id"), nullable=False)
    date = Column(Date, nullable=False)
    time = Column(Time, nullable=False)
    duration_minutes = Column(Integer, default=15, nullable=False)
    status = Column(String(20), default="booked", nullable=False)  # booked, confirmed, entered_in_ehr, cancelled, no_show, completed
    insurance_verified = Column(Boolean, default=False, nullable=False)
    insurance_verification_result = Column(JSON, nullable=True)
    booked_by = Column(String(20), default="ai", nullable=False)
    call_id = Column(UUID(as_uuid=True), nullable=True)
    notes = Column(Text, nullable=True)
    sms_confirmation_sent = Column(Boolean, default=False, nullable=False)
    entered_in_ehr_at = Column(DateTime(timezone=True), nullable=True)
    entered_in_ehr_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships — patient and type loaded eagerly (needed for display),
    # practice and ehr_user lazy (rarely needed in the same query)
    practice = relationship("Practice", back_populates="appointments", lazy="select")
    patient = relationship("Patient", back_populates="appointments", lazy="selectin")
    appointment_type = relationship("AppointmentType", back_populates="appointments", lazy="selectin")
    ehr_user = relationship("User", foreign_keys=[entered_in_ehr_by], lazy="select")

    def __repr__(self):
        return f"<Appointment(id={self.id}, date={self.date}, time={self.time}, status='{self.status}')>"
