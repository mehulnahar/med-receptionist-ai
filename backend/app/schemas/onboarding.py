"""Pydantic schemas for the self-service onboarding wizard."""

from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Vapi
# ---------------------------------------------------------------------------

class ValidateVapiKeyRequest(BaseModel):
    api_key: str = Field(..., min_length=1, description="Vapi API key to validate")


class ValidateVapiKeyResponse(BaseModel):
    valid: bool
    message: str
    account_name: Optional[str] = None


class CreateAssistantRequest(BaseModel):
    system_prompt: Optional[str] = Field(None, description="Custom system prompt (uses default if omitted)")
    first_message: Optional[str] = Field(None, description="Custom first message (uses default if omitted)")


class CreateAssistantResponse(BaseModel):
    success: bool
    assistant_id: Optional[str] = None
    assistant_name: Optional[str] = None
    message: str


class VapiPhoneNumber(BaseModel):
    id: str
    number: Optional[str] = None
    name: Optional[str] = None
    assigned_assistant_id: Optional[str] = None
    provider: Optional[str] = None


class VapiPhoneListResponse(BaseModel):
    phone_numbers: list[VapiPhoneNumber]
    total: int


class AssignPhoneRequest(BaseModel):
    phone_number_id: str = Field(..., min_length=1, description="Vapi phone number ID to assign")


class AssignPhoneResponse(BaseModel):
    success: bool
    phone_number_id: str
    phone_number: Optional[str] = None
    message: str


# ---------------------------------------------------------------------------
# Twilio
# ---------------------------------------------------------------------------

class ValidateTwilioRequest(BaseModel):
    account_sid: str = Field(..., min_length=1, description="Twilio Account SID")
    auth_token: str = Field(..., min_length=1, description="Twilio Auth Token")


class ValidateTwilioResponse(BaseModel):
    valid: bool
    message: str
    account_name: Optional[str] = None


class TwilioPhoneNumber(BaseModel):
    sid: str
    phone_number: str
    friendly_name: Optional[str] = None
    sms_enabled: bool = False
    voice_enabled: bool = False


class TwilioPhoneListResponse(BaseModel):
    phone_numbers: list[TwilioPhoneNumber]
    total: int


class SaveTwilioConfigRequest(BaseModel):
    account_sid: str = Field(..., min_length=1)
    auth_token: str = Field(..., min_length=1)
    phone_number: str = Field(..., min_length=1, description="Selected Twilio phone number (E.164)")


class SaveTwilioConfigResponse(BaseModel):
    success: bool
    message: str


# ---------------------------------------------------------------------------
# OpenAI Key Validation
# ---------------------------------------------------------------------------

class ValidateOpenAIKeyRequest(BaseModel):
    api_key: str = Field(..., min_length=1, description="OpenAI API key to validate")


class ValidateOpenAIKeyResponse(BaseModel):
    valid: bool
    message: str


# ---------------------------------------------------------------------------
# Stedi Key Validation
# ---------------------------------------------------------------------------

class ValidateStediKeyRequest(BaseModel):
    api_key: str = Field(..., min_length=1, description="Stedi API key to validate")


class ValidateStediKeyResponse(BaseModel):
    valid: bool
    message: str


# ---------------------------------------------------------------------------
# Onboarding Status
# ---------------------------------------------------------------------------

class OnboardingStepStatus(BaseModel):
    completed: bool
    detail: Optional[str] = None  # e.g. assistant ID, phone number


class OnboardingStatusResponse(BaseModel):
    vapi_key: OnboardingStepStatus
    vapi_assistant: OnboardingStepStatus
    vapi_phone: OnboardingStepStatus
    twilio_credentials: OnboardingStepStatus
    twilio_phone: OnboardingStepStatus
    openai_key: OnboardingStepStatus
    stedi_key: OnboardingStepStatus
    all_complete: bool
