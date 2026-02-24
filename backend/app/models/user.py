import uuid

from sqlalchemy import Column, String, Boolean, DateTime, Integer, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id", ondelete="SET NULL"), nullable=True)  # null for super_admin
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False)  # super_admin, practice_admin, secretary
    is_active = Column(Boolean, default=True, nullable=False)
    password_change_required = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    last_login = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # HIPAA: Account lockout
    failed_login_attempts = Column(Integer, default=0, nullable=False, server_default=text("0"))
    locked_until = Column(DateTime(timezone=True), nullable=True)
    last_password_change = Column(DateTime(timezone=True), nullable=True)

    # HIPAA: MFA (TOTP)
    mfa_secret = Column(String(300), nullable=True)
    mfa_enabled = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    mfa_backup_codes = Column(JSON, nullable=True)

    # Relationships
    practice = relationship("Practice", back_populates="users", lazy="select")

    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}', role='{self.role}')>"
