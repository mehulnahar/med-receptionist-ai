import uuid

from sqlalchemy import Column, String, Text, DateTime, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Practice(Base):
    __tablename__ = "practices"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    npi = Column(String(10), nullable=False)
    tax_id = Column(String(9), nullable=False)
    phone = Column(String(20), nullable=True)
    address = Column(Text, nullable=True)
    timezone = Column(String(50), nullable=False, default="America/New_York")
    status = Column(String(20), nullable=False, default="setup")  # setup, active, paused, inactive
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    users = relationship("User", back_populates="practice", lazy="selectin")
    config = relationship("PracticeConfig", back_populates="practice", uselist=False, lazy="selectin")
    schedule_templates = relationship("ScheduleTemplate", back_populates="practice", lazy="selectin")
    schedule_overrides = relationship("ScheduleOverride", back_populates="practice", lazy="selectin")
    appointment_types = relationship("AppointmentType", back_populates="practice", lazy="selectin")
    insurance_carriers = relationship("InsuranceCarrier", back_populates="practice", lazy="selectin")
    patients = relationship("Patient", back_populates="practice", lazy="selectin")
    appointments = relationship("Appointment", back_populates="practice", lazy="selectin")
    calls = relationship("Call", back_populates="practice", lazy="selectin")
    insurance_verifications = relationship("InsuranceVerification", back_populates="practice", lazy="selectin")

    def __repr__(self):
        return f"<Practice(id={self.id}, name='{self.name}', slug='{self.slug}')>"
