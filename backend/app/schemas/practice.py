from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional


class PracticeBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern="^[a-z0-9-]+$")
    npi: str = Field(..., min_length=10, max_length=10)
    tax_id: str = Field(..., min_length=9, max_length=9)
    phone: str | None = None
    address: str | None = None
    timezone: str = "America/New_York"


class PracticeCreate(PracticeBase):
    pass


class PracticeUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    phone: str | None = None
    address: str | None = None
    timezone: str | None = None
    status: str | None = Field(None, pattern="^(setup|active|paused|inactive)$")


class PracticeResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    npi: str
    tax_id: str
    phone: str | None = None
    address: str | None = None
    timezone: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PracticeListResponse(BaseModel):
    practices: list[PracticeResponse]
    total: int
