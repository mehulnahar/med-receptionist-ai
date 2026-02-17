import uuid

from sqlalchemy import Column, String, Integer, Date, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Holiday(Base):
    __tablename__ = "holidays"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    date = Column(Date, nullable=False)
    name = Column(String(255), nullable=False)
    year = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("date", name="uq_holiday_date"),
    )

    def __repr__(self):
        return f"<Holiday(id={self.id}, date={self.date}, name='{self.name}')>"
