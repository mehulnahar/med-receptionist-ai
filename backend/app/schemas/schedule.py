from pydantic import BaseModel, Field, field_validator, model_validator
from uuid import UUID
from datetime import date, time


# --- Schedule Template ---

class ScheduleTemplateResponse(BaseModel):
    id: UUID
    day_of_week: int = Field(..., ge=0, le=6, description="0=Monday, 6=Sunday")
    is_enabled: bool
    start_time: time | None = None
    end_time: time | None = None

    model_config = {"from_attributes": True}


class ScheduleTemplateUpdate(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6, description="0=Monday, 6=Sunday")
    is_enabled: bool
    start_time: time | None = None
    end_time: time | None = None

    @field_validator("end_time")
    @classmethod
    def end_time_after_start_time(cls, v: time | None, info) -> time | None:
        start = info.data.get("start_time")
        if v is not None and start is not None and v <= start:
            raise ValueError("end_time must be after start_time")
        return v

    @model_validator(mode="after")
    def enabled_requires_times(self) -> "ScheduleTemplateUpdate":
        if self.is_enabled and (self.start_time is None or self.end_time is None):
            raise ValueError("start_time and end_time are required when is_enabled is True")
        return self


class ScheduleWeekResponse(BaseModel):
    schedules: list[ScheduleTemplateResponse] = Field(
        ..., min_length=7, max_length=7, description="7 entries, Mon-Sun"
    )


# --- Schedule Override ---

class ScheduleOverrideResponse(BaseModel):
    id: UUID
    date: date
    is_working: bool
    start_time: time | None = None
    end_time: time | None = None
    reason: str | None = None
    created_by: UUID | None = None

    model_config = {"from_attributes": True}


class ScheduleOverrideCreate(BaseModel):
    date: date
    is_working: bool
    start_time: time | None = None
    end_time: time | None = None
    reason: str | None = Field(None, max_length=255)

    # NOTE: Past-date validation was moved to the route handler
    # (create_schedule_override) where practice timezone is available.

    @field_validator("end_time")
    @classmethod
    def end_time_after_start_time(cls, v: time | None, info) -> time | None:
        start = info.data.get("start_time")
        if v is not None and start is not None and v <= start:
            raise ValueError("end_time must be after start_time")
        return v


class ScheduleOverrideListResponse(BaseModel):
    overrides: list[ScheduleOverrideResponse]
    total: int


# --- Availability ---

class AvailableSlot(BaseModel):
    time: time
    is_available: bool
    current_bookings: int = 0


class AvailabilityResponse(BaseModel):
    date: date
    slots: list[AvailableSlot]
    is_working_day: bool
