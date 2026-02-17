import uuid

from sqlalchemy import Column, String, Integer, Boolean, Date, Time, DateTime, ForeignKey, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class ScheduleTemplate(Base):
    __tablename__ = "schedule_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id"), nullable=False)
    day_of_week = Column(Integer, nullable=False)  # 0=Monday, 6=Sunday
    is_enabled = Column(Boolean, default=True, nullable=False)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)

    __table_args__ = (
        UniqueConstraint("practice_id", "day_of_week", name="uq_schedule_template_practice_day"),
    )

    # Relationships
    practice = relationship("Practice", back_populates="schedule_templates", lazy="selectin")

    def __repr__(self):
        return f"<ScheduleTemplate(id={self.id}, practice_id={self.practice_id}, day={self.day_of_week})>"


class ScheduleOverride(Base):
    __tablename__ = "schedule_overrides"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id"), nullable=False)
    date = Column(Date, nullable=False)
    is_working = Column(Boolean, default=False, nullable=False)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    reason = Column(String(255), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint("practice_id", "date", name="uq_schedule_override_practice_date"),
    )

    # Relationships
    practice = relationship("Practice", back_populates="schedule_overrides", lazy="selectin")
    creator = relationship("User", lazy="selectin")

    def __repr__(self):
        return f"<ScheduleOverride(id={self.id}, practice_id={self.practice_id}, date={self.date})>"
