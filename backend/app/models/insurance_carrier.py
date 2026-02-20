import uuid

from sqlalchemy import Column, Index, String, Boolean, ForeignKey, UniqueConstraint, text, func
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship

from app.database import Base


class InsuranceCarrier(Base):
    __tablename__ = "insurance_carriers"
    __table_args__ = (
        Index(
            "ix_insurance_carriers_practice_name",
            "practice_id",
            func.lower("name"),
            unique=True,
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    aliases = Column(JSON, default=[], nullable=False)
    stedi_payer_id = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    practice = relationship("Practice", back_populates="insurance_carriers", lazy="select")

    def __repr__(self):
        return f"<InsuranceCarrier(id={self.id}, name='{self.name}')>"
