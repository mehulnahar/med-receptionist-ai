from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from datetime import date, time, datetime, timedelta
from typing import Any


APPOINTMENT_STATUSES = (
    "booked", "confirmed", "entered_in_ehr", "cancelled", "no_show", "completed"
)

MAX_BOOKING_DAYS_AHEAD = 365


def _validate_appointment_date(v: date) -> date:
    """Reject dates in the past or more than 365 days in the future."""
    today = date.today()
    if v < today:
        raise ValueError("Appointment date cannot be in the past")
    if v > today + timedelta(days=MAX_BOOKING_DAYS_AHEAD):
        raise ValueError(f"Appointment date cannot be more than {MAX_BOOKING_DAYS_AHEAD} days in the future")
    return v


class BookAppointmentRequest(BaseModel):
    patient_id: UUID
    appointment_type_id: UUID
    date: date
    time: time
    notes: str | None = Field(None, max_length=2000)
    booked_by: str = Field(default="ai", max_length=20)
    call_id: UUID | None = None

    @field_validator("date")
    @classmethod
    def date_in_range(cls, v: date) -> date:
        return _validate_appointment_date(v)


class AppointmentResponse(BaseModel):
    id: UUID
    practice_id: UUID
    patient_id: UUID
    appointment_type_id: UUID
    date: date
    time: time
    duration_minutes: int
    status: str
    insurance_verified: bool
    insurance_verification_result: dict[str, Any] | None = None
    booked_by: str
    call_id: UUID | None = None
    notes: str | None = None
    sms_confirmation_sent: bool
    entered_in_ehr_at: datetime | None = None
    entered_in_ehr_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    # Computed / joined fields
    patient_name: str = ""
    appointment_type_name: str = ""

    model_config = {"from_attributes": True}


class AppointmentListResponse(BaseModel):
    appointments: list[AppointmentResponse]
    total: int


class CancelAppointmentRequest(BaseModel):
    reason: str | None = Field(None, max_length=1000)


class RescheduleAppointmentRequest(BaseModel):
    new_date: date
    new_time: time
    notes: str | None = Field(None, max_length=2000)

    @field_validator("new_date")
    @classmethod
    def date_in_range(cls, v: date) -> date:
        return _validate_appointment_date(v)


class ConfirmAppointmentRequest(BaseModel):
    notes: str | None = Field(None, max_length=2000)


class AppointmentStatusUpdate(BaseModel):
    status: str = Field(
        ...,
        pattern="^(booked|confirmed|entered_in_ehr|cancelled|no_show|completed)$",
    )
    notes: str | None = Field(None, max_length=2000)
