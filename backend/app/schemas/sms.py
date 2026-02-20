from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime


class SendSmsRequest(BaseModel):
    """Request body for sending a custom SMS."""
    to_number: str = Field(
        ...,
        description="Recipient phone number in E.164 format, e.g. '+12125551234'",
        pattern=r"^\+[1-9]\d{1,14}$",
    )
    body: str = Field(
        ...,
        description="SMS message body",
        min_length=1,
        max_length=1600,
    )


class SendConfirmationRequest(BaseModel):
    """Request body for triggering an appointment confirmation SMS."""
    appointment_id: UUID


class SmsResponse(BaseModel):
    """Response returned from any SMS send operation."""
    success: bool
    message_sid: str | None = None
    to: str | None = None
    body: str | None = None
    error: str | None = None


class SmsHistoryEntry(BaseModel):
    """Single entry in the SMS history list (future use)."""
    id: UUID
    appointment_id: UUID | None = None
    to_number: str
    body: str
    status: str = Field(
        ...,
        description="Delivery status: sent, delivered, or failed",
    )
    message_sid: str | None = None
    sent_at: datetime

    model_config = {"from_attributes": True}
