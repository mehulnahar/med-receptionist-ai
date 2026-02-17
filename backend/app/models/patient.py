import uuid

from sqlalchemy import Column, String, Boolean, Text, Date, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id"), nullable=False)
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=False)
    dob = Column(Date, nullable=False)
    phone = Column(String(20), nullable=True)
    address = Column(Text, nullable=True)
    insurance_carrier = Column(String(255), nullable=True)
    member_id = Column(String(100), nullable=True)
    group_number = Column(String(100), nullable=True)
    referring_physician = Column(String(255), nullable=True)
    accident_date = Column(Date, nullable=True)
    accident_type = Column(String(50), nullable=True)  # workers_comp, no_fault
    is_new = Column(Boolean, default=True, nullable=False)
    language_preference = Column(String(5), default="en", nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    practice = relationship("Practice", back_populates="patients", lazy="selectin")
    appointments = relationship("Appointment", back_populates="patient", lazy="selectin")
    calls = relationship("Call", back_populates="patient", lazy="selectin")
    insurance_verifications = relationship("InsuranceVerification", back_populates="patient", lazy="selectin")

    def __repr__(self):
        return f"<Patient(id={self.id}, name='{self.first_name} {self.last_name}')>"
