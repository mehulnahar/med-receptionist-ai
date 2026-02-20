import uuid

from sqlalchemy import Column, Index, UniqueConstraint, String, Boolean, Text, Date, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (
        Index("ix_patients_practice_name", "practice_id", "last_name", "first_name"),
        Index("ix_patients_practice_dob", "practice_id", "dob"),
        # Race-condition guard: prevents duplicate patients even under concurrent inserts
        UniqueConstraint("practice_id", "first_name", "last_name", "dob", name="uq_patients_practice_name_dob"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), nullable=False)
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

    # Relationships — collections lazy-loaded to avoid fetching all history on every query
    practice = relationship("Practice", back_populates="patients", lazy="select")
    appointments = relationship("Appointment", back_populates="patient", lazy="select")
    calls = relationship("Call", back_populates="patient", lazy="select")
    insurance_verifications = relationship("InsuranceVerification", back_populates="patient", lazy="select")

    def __repr__(self):
        return f"<Patient(id={self.id}, name='{self.first_name} {self.last_name}')>"
