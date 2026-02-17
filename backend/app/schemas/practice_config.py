from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Any


class PracticeConfigResponse(BaseModel):
    id: UUID
    practice_id: UUID

    # Telephony - Twilio
    twilio_phone_number: str | None = None
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None

    # Telephony - Vonage forwarding
    vonage_forwarding_enabled: bool = False
    vonage_forwarding_number: str | None = None

    # Vapi
    vapi_api_key: str | None = None
    vapi_agent_id: str | None = None
    vapi_assistant_id: str | None = None
    vapi_phone_number_id: str | None = None
    vapi_system_prompt: str | None = None
    vapi_first_message: str | None = None
    vapi_model_provider: str = "openai"
    vapi_model_name: str = "gpt-4o-mini"
    vapi_voice_provider: str = "11labs"
    vapi_voice_id: str | None = None

    # Insurance - Stedi
    stedi_api_key: str | None = None
    stedi_enabled: bool = False
    insurance_verification_on_call: bool = True

    # Languages
    languages: list[str] = Field(default_factory=lambda: ["en"])
    primary_language: str = "en"
    greek_transfer_to_staff: bool = True

    # Slots
    slot_duration_minutes: int = 15
    allow_overbooking: bool = False
    max_overbooking_per_slot: int = 2
    booking_horizon_days: int = 90

    # Greetings
    greetings: dict[str, Any] = Field(default_factory=dict)

    # Transfer
    transfer_number: str | None = None
    emergency_message: str | None = None

    # SMS
    sms_confirmation_enabled: bool = True
    sms_confirmation_template: dict[str, Any] = Field(default_factory=dict)

    # Data fields
    new_patient_fields: list[str] | None = None
    existing_patient_fields: list[str] | None = None

    # Conversation
    system_prompt: str | None = None
    fallback_message: str | None = None
    max_retries: int = 3

    # Timestamps
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PracticeConfigUpdate(BaseModel):
    # Telephony - Twilio
    twilio_phone_number: str | None = None
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None

    # Telephony - Vonage forwarding
    vonage_forwarding_enabled: bool | None = None
    vonage_forwarding_number: str | None = None

    # Vapi
    vapi_api_key: str | None = None
    vapi_agent_id: str | None = None
    vapi_assistant_id: str | None = None
    vapi_phone_number_id: str | None = None
    vapi_system_prompt: str | None = None
    vapi_first_message: str | None = None
    vapi_model_provider: str | None = None
    vapi_model_name: str | None = None
    vapi_voice_provider: str | None = None
    vapi_voice_id: str | None = None

    # Insurance - Stedi
    stedi_api_key: str | None = None
    stedi_enabled: bool | None = None
    insurance_verification_on_call: bool | None = None

    # Languages
    languages: list[str] | None = None
    primary_language: str | None = None
    greek_transfer_to_staff: bool | None = None

    # Slots
    slot_duration_minutes: int | None = Field(None, ge=5, le=120)
    allow_overbooking: bool | None = None
    max_overbooking_per_slot: int | None = Field(None, ge=1, le=10)
    booking_horizon_days: int | None = Field(None, ge=1, le=365)

    # Greetings
    greetings: dict[str, Any] | None = None

    # Transfer
    transfer_number: str | None = None
    emergency_message: str | None = None

    # SMS
    sms_confirmation_enabled: bool | None = None
    sms_confirmation_template: dict[str, Any] | None = None

    # Data fields
    new_patient_fields: list[str] | None = None
    existing_patient_fields: list[str] | None = None

    # Conversation
    system_prompt: str | None = None
    fallback_message: str | None = None
    max_retries: int | None = Field(None, ge=1, le=10)
