import uuid

from sqlalchemy import Column, String, Integer, Date, ForeignKey, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Holiday(Base):
    __tablename__ = "holidays"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    name = Column(String(255), nullable=False)
    year = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("practice_id", "date", name="uq_holiday_practice_date"),
    )

    # Relationships
    practice = relationship("Practice", back_populates="holidays", lazy="select")

    def __repr__(self):
        return f"<Holiday(id={self.id}, practice_id={self.practice_id}, date={self.date}, name='{self.name}')>"
