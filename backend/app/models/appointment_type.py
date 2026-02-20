import uuid

from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, CheckConstraint, text
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class AppointmentType(Base):
    __tablename__ = "appointment_types"
    __table_args__ = (
        CheckConstraint(
            "duration_minutes >= 5 AND duration_minutes <= 480",
            name="ck_appointment_types_duration",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    color = Column(String(7), default="#6B7280", nullable=False)
    duration_minutes = Column(Integer, default=15, nullable=False)
    for_new_patients = Column(Boolean, default=False, nullable=False)
    for_existing_patients = Column(Boolean, default=False, nullable=False)
    requires_accident_date = Column(Boolean, default=False, nullable=False)
    requires_referral = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    detection_rules = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    practice = relationship("Practice", back_populates="appointment_types", lazy="select")
    appointments = relationship("Appointment", back_populates="appointment_type", lazy="select")

    def __repr__(self):
        return f"<AppointmentType(id={self.id}, name='{self.name}')>"
