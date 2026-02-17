from pydantic import BaseModel, Field
from uuid import UUID
from datetime import date, time, datetime
from typing import Any


APPOINTMENT_STATUSES = (
    "booked", "confirmed", "entered_in_ehr", "cancelled", "no_show", "completed"
)


class BookAppointmentRequest(BaseModel):
    patient_id: UUID
    appointment_type_id: UUID
    date: date
    time: time
    notes: str | None = None
    booked_by: str = Field(default="ai", max_length=20)
    call_id: UUID | None = None


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
    reason: str | None = None


class RescheduleAppointmentRequest(BaseModel):
    new_date: date
    new_time: time
    notes: str | None = None


class ConfirmAppointmentRequest(BaseModel):
    notes: str | None = None


class AppointmentStatusUpdate(BaseModel):
    status: str = Field(
        ...,
        pattern="^(booked|confirmed|entered_in_ehr|cancelled|no_show|completed)$",
    )
    notes: str | None = None
