import uuid

from sqlalchemy import Column, Index, String, Boolean, DateTime, Numeric, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class InsuranceVerification(Base):
    __tablename__ = "insurance_verifications"
    __table_args__ = (
        Index("ix_ins_verif_practice_patient", "practice_id", "patient_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), nullable=False)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    call_id = Column(UUID(as_uuid=True), ForeignKey("calls.id"), nullable=True)
    carrier_name = Column(String(255), nullable=True)
    member_id = Column(String(100), nullable=True)
    payer_id = Column(String(50), nullable=True)
    request_payload = Column(JSON, nullable=True)
    response_payload = Column(JSON, nullable=True)
    is_active = Column(Boolean, nullable=True)
    copay = Column(Numeric(10, 2), nullable=True)
    plan_name = Column(String(255), nullable=True)
    status = Column(String(20), nullable=True)
    verified_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    practice = relationship("Practice", back_populates="insurance_verifications", lazy="select")
    patient = relationship("Patient", back_populates="insurance_verifications", lazy="selectin")
    call = relationship("Call", lazy="select")

    def __repr__(self):
        return f"<InsuranceVerification(id={self.id}, carrier='{self.carrier_name}', status='{self.status}')>"
