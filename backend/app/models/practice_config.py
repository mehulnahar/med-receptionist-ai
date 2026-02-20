import uuid

from sqlalchemy import Column, String, Integer, Boolean, Text, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base
from app.utils.encryption import EncryptedString


class PracticeConfig(Base):
    __tablename__ = "practice_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    practice_id = Column(UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), unique=True, nullable=False)

    # Telephony - Twilio
    twilio_phone_number = Column(String(20), nullable=True)
    twilio_account_sid = Column(EncryptedString(300), nullable=True)
    twilio_auth_token = Column(EncryptedString(300), nullable=True)

    # Telephony - Vonage forwarding
    vonage_forwarding_enabled = Column(Boolean, default=False, nullable=False)
    vonage_forwarding_number = Column(String(20), nullable=True)

    # Vapi
    vapi_api_key = Column(EncryptedString(500), nullable=True)
    vapi_agent_id = Column(String(100), nullable=True)
    vapi_assistant_id = Column(String(100), nullable=True)
    vapi_phone_number_id = Column(String(100), nullable=True)
    vapi_system_prompt = Column(Text, nullable=True)
    vapi_first_message = Column(Text, nullable=True)
    vapi_model_provider = Column(String(50), default="openai", nullable=False)
    vapi_model_name = Column(String(50), default="gpt-4o-mini", nullable=False)
    vapi_voice_provider = Column(String(50), default="11labs", nullable=False)
    vapi_voice_id = Column(String(100), nullable=True)

    # Insurance - Stedi
    stedi_api_key = Column(EncryptedString(500), nullable=True)
    stedi_enabled = Column(Boolean, default=False, nullable=False)
    insurance_verification_on_call = Column(Boolean, default=True, nullable=False)

    # Languages
    languages = Column(JSON, default=lambda: ["en"], nullable=False)
    primary_language = Column(String(5), default="en", nullable=False)
    greek_transfer_to_staff = Column(Boolean, default=True, nullable=False)

    # Slots
    slot_duration_minutes = Column(Integer, default=15, nullable=False)
    allow_overbooking = Column(Boolean, default=False, nullable=False)
    max_overbooking_per_slot = Column(Integer, default=2, nullable=False)
    booking_horizon_days = Column(Integer, default=90, nullable=False)

    # Greetings
    greetings = Column(JSON, default=dict, nullable=False)

    # Transfer
    transfer_number = Column(String(20), nullable=True)
    emergency_message = Column(Text, nullable=True)

    # SMS
    sms_confirmation_enabled = Column(Boolean, default=True, nullable=False)
    sms_confirmation_template = Column(JSON, default=dict, nullable=False)

    # Data fields
    new_patient_fields = Column(JSON, nullable=True)
    existing_patient_fields = Column(JSON, nullable=True)

    # Conversation
    system_prompt = Column(Text, nullable=True)
    fallback_message = Column(Text, nullable=True)
    max_retries = Column(Integer, default=3, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    practice = relationship("Practice", back_populates="config", lazy="select")

    def __repr__(self):
        return f"<PracticeConfig(id={self.id}, practice_id={self.practice_id})>"
