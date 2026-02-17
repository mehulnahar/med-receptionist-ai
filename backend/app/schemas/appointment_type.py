from pydantic import BaseModel, Field
from uuid import UUID
from typing import Any


class AppointmentTypeBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    color: str = Field(default="#6B7280", max_length=7, pattern="^#[0-9A-Fa-f]{6}$")
    duration_minutes: int = Field(default=15, ge=5, le=240)
    for_new_patients: bool = False
    for_existing_patients: bool = False
    requires_accident_date: bool = False
    requires_referral: bool = False
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0)
    detection_rules: dict[str, Any] | None = None


class AppointmentTypeCreate(AppointmentTypeBase):
    pass


class AppointmentTypeUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    color: str | None = Field(None, max_length=7, pattern="^#[0-9A-Fa-f]{6}$")
    duration_minutes: int | None = Field(None, ge=5, le=240)
    for_new_patients: bool | None = None
    for_existing_patients: bool | None = None
    requires_accident_date: bool | None = None
    requires_referral: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = Field(None, ge=0)
    detection_rules: dict[str, Any] | None = None


class AppointmentTypeResponse(AppointmentTypeBase):
    id: UUID

    model_config = {"from_attributes": True}


class AppointmentTypeListResponse(BaseModel):
    appointment_types: list[AppointmentTypeResponse]
    total: int
