"""Pydantic schemas for insurance verification endpoints."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class InsuranceVerificationRequest(BaseModel):
    """POST body for triggering an insurance eligibility check."""

    carrier_name: str = Field(..., min_length=1, max_length=255, description="Insurance carrier name, e.g. 'Aetna'")
    member_id: str = Field(..., min_length=1, max_length=100, description="Member/subscriber ID on the insurance card")
    first_name: str | None = Field(None, min_length=1, max_length=255, description="Patient first name (required if patient_id not provided)")
    last_name: str | None = Field(None, min_length=1, max_length=255, description="Patient last name (required if patient_id not provided)")
    date_of_birth: date | None = Field(None, description="Patient date of birth in YYYY-MM-DD format (required if patient_id not provided)")
    patient_id: UUID | None = Field(None, description="Existing patient UUID; if provided, name/dob lookup is skipped")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class InsuranceVerificationResponse(BaseModel):
    """Single insurance verification result returned by the API."""

    id: UUID
    practice_id: UUID
    patient_id: UUID | None = None
    carrier_name: str | None = None
    member_id: str | None = None
    payer_id: str | None = None
    is_active: bool | None = None
    copay: Decimal | None = None
    plan_name: str | None = None
    status: str | None = Field(None, description="Verification outcome: success, failed, timeout, error")
    verified_at: datetime | None = None
    message: str = Field("", description="Human-readable result summary")

    model_config = {"from_attributes": True}


class InsuranceVerificationListResponse(BaseModel):
    """Paginated list of insurance verifications."""

    verifications: list[InsuranceVerificationResponse]
    total: int


# ---------------------------------------------------------------------------
# Internal / service-layer schemas
# ---------------------------------------------------------------------------


class InsuranceEligibilityResult(BaseModel):
    """Parsed eligibility result from the Stedi API (used internally by the insurance service)."""

    is_active: bool
    plan_name: str = ""
    copay: Decimal | None = None
    group_number: str = ""
    carrier: str = ""
    member_id: str = ""
    error: str | None = None
    raw_benefits: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Carrier lookup
# ---------------------------------------------------------------------------


class CarrierLookupResponse(BaseModel):
    """Result of a fuzzy carrier-name lookup against known payers."""

    found: bool
    carrier_name: str | None = None
    payer_id: str | None = None
    aliases: list[str] = Field(default_factory=list)
