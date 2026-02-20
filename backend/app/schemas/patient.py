from pydantic import BaseModel, Field, model_validator
from uuid import UUID
from datetime import date, datetime
from typing import Optional


class PatientBase(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=255)
    last_name: str = Field(..., min_length=1, max_length=255)
    dob: date
    phone: str | None = Field(None, max_length=20)
    address: str | None = Field(None, max_length=500)
    insurance_carrier: str | None = Field(None, max_length=255)
    member_id: str | None = Field(None, max_length=100)
    group_number: str | None = Field(None, max_length=100)
    referring_physician: str | None = Field(None, max_length=255)
    accident_date: date | None = None
    accident_type: str | None = Field(
        None, pattern="^(workers_comp|no_fault)$"
    )
    language_preference: str | None = Field("en", max_length=5)
    notes: str | None = Field(None, max_length=5000)


class PatientCreate(PatientBase):
    pass


class PatientUpdate(BaseModel):
    first_name: str | None = Field(None, min_length=1, max_length=255)
    last_name: str | None = Field(None, min_length=1, max_length=255)
    dob: date | None = None
    phone: str | None = Field(None, max_length=20)
    address: str | None = Field(None, max_length=500)
    insurance_carrier: str | None = Field(None, max_length=255)
    member_id: str | None = Field(None, max_length=100)
    group_number: str | None = Field(None, max_length=100)
    referring_physician: str | None = Field(None, max_length=255)
    accident_date: date | None = None
    accident_type: str | None = Field(
        None, pattern="^(workers_comp|no_fault)$"
    )
    language_preference: str | None = Field(None, max_length=5)
    notes: str | None = Field(None, max_length=5000)


class PatientResponse(PatientBase):
    id: UUID
    practice_id: UUID
    is_new: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PatientSearchRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    dob: date | None = None
    phone: str | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> "PatientSearchRequest":
        if not any([self.first_name, self.last_name, self.dob, self.phone]):
            raise ValueError(
                "At least one search field must be provided "
                "(first_name, last_name, dob, or phone)"
            )
        return self


class PatientListResponse(BaseModel):
    patients: list[PatientResponse]
    total: int
