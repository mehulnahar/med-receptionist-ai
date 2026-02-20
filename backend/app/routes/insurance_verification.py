"""Insurance verification endpoints — eligibility checks, history, and carrier lookup."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.database import get_db
from app.models.user import User
from app.models.patient import Patient
from app.models.insurance_carrier import InsuranceCarrier
from app.models.insurance_verification import InsuranceVerification
from app.schemas.insurance_verification import (
    InsuranceVerificationRequest,
    InsuranceVerificationResponse,
    InsuranceVerificationListResponse,
    CarrierLookupResponse,
)
from app.middleware.auth import get_current_user, require_any_staff
from app.services.insurance_service import (
    check_eligibility,
    resolve_payer_id,
)

router = APIRouter()


def _ensure_practice(user: User) -> UUID:
    """Return the user's practice_id or raise 400 if it is None."""
    if not user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )
    return user.practice_id


def _build_message(verification: InsuranceVerification) -> str:
    """Build a human-readable summary message from a verification record."""
    if verification.status in ("failed", "timeout", "error"):
        error_detail = ""
        if verification.response_payload and isinstance(verification.response_payload, dict):
            error_detail = verification.response_payload.get("error", "")
        return f"Verification failed: {error_detail or verification.status}"

    if verification.is_active is None:
        return "Verification completed but coverage status is unknown"

    if not verification.is_active:
        return "Coverage is inactive"

    # Active coverage
    parts = ["Coverage is active"]
    if verification.copay is not None:
        parts.append(f"Copay: ${verification.copay:.2f}")
    if verification.plan_name:
        parts.append(f"Plan: {verification.plan_name}")
    return ". ".join(parts)


# ---------------------------------------------------------------------------
# Verify insurance (POST /verify)
# ---------------------------------------------------------------------------


@router.post("/verify", response_model=InsuranceVerificationResponse)
async def verify_insurance(
    request: InsuranceVerificationRequest,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Run an insurance eligibility check via Stedi.

    If patient_id is provided, uses it directly. Otherwise, looks up the
    patient by first_name + last_name + date_of_birth within the practice.
    """
    practice_id = _ensure_practice(current_user)

    # Resolve patient
    if request.patient_id:
        result = await db.execute(
            select(Patient).where(
                Patient.id == request.patient_id,
                Patient.practice_id == practice_id,
            )
        )
        patient = result.scalar_one_or_none()
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found",
            )
    else:
        # Look up by name + dob
        if not request.first_name or not request.last_name or not request.date_of_birth:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either patient_id or first_name + last_name + date_of_birth must be provided",
            )
        result = await db.execute(
            select(Patient).where(
                Patient.practice_id == practice_id,
                func.lower(Patient.first_name) == request.first_name.lower(),
                func.lower(Patient.last_name) == request.last_name.lower(),
                Patient.dob == request.date_of_birth,
            ).limit(1)
        )
        patient = result.scalar_one_or_none()
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient not found matching the provided name and date of birth",
            )

    # Call the insurance service with proper arguments
    try:
        eligibility_result = await check_eligibility(
            db=db,
            practice_id=practice_id,
            patient_id=patient.id,
            carrier_name=request.carrier_name,
            member_id=request.member_id,
            first_name=patient.first_name,
            last_name=patient.last_name,
            dob=patient.dob,
        )
    except Exception as exc:
        logger.exception("Insurance eligibility check failed for patient %s", patient.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Insurance verification service is temporarily unavailable. Please try again later.",
        ) from exc

    # The service returns a dict; now fetch the latest verification record
    # for this patient to build the response from the ORM model
    stmt = (
        select(InsuranceVerification)
        .where(
            InsuranceVerification.practice_id == practice_id,
            InsuranceVerification.patient_id == patient.id,
        )
        .order_by(InsuranceVerification.verified_at.desc())
        .limit(1)
    )
    db_result = await db.execute(stmt)
    verification = db_result.scalar_one_or_none()

    if verification:
        response = InsuranceVerificationResponse.model_validate(verification)
        response.message = _build_message(verification)
        return response

    # Fallback: build response from the dict (shouldn't happen normally)
    return InsuranceVerificationResponse(
        id=UUID("00000000-0000-0000-0000-000000000000"),
        practice_id=practice_id,
        patient_id=patient.id,
        carrier_name=eligibility_result.get("carrier"),
        member_id=eligibility_result.get("member_id"),
        is_active=eligibility_result.get("is_active"),
        copay=eligibility_result.get("copay"),
        plan_name=eligibility_result.get("plan_name"),
        status="failed" if eligibility_result.get("error") else "success",
        message=eligibility_result.get("error") or "Verification complete",
    )


# ---------------------------------------------------------------------------
# Carrier lookup (GET /lookup-carrier)
# ---------------------------------------------------------------------------


@router.get("/lookup-carrier", response_model=CarrierLookupResponse)
async def lookup_carrier(
    carrier_name: str = Query(..., min_length=1, description="Carrier name to search for"),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Fuzzy-match a carrier name and return the resolved payer information."""
    practice_id = _ensure_practice(current_user)

    payer_id, matched_name = await resolve_payer_id(
        db=db,
        practice_id=practice_id,
        carrier_name=carrier_name,
    )

    if not payer_id:
        return CarrierLookupResponse(found=False)

    # Fetch the carrier record to get aliases
    stmt = select(InsuranceCarrier).where(
        InsuranceCarrier.practice_id == practice_id,
        InsuranceCarrier.name == matched_name,
    )
    result = await db.execute(stmt)
    carrier = result.scalar_one_or_none()

    return CarrierLookupResponse(
        found=True,
        carrier_name=matched_name,
        payer_id=payer_id,
        aliases=carrier.aliases if carrier and carrier.aliases else [],
    )


# ---------------------------------------------------------------------------
# List verifications (GET /)
# ---------------------------------------------------------------------------


@router.get("/", response_model=InsuranceVerificationListResponse)
async def list_verifications(
    patient_id: UUID | None = Query(None, description="Filter by patient ID"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """List insurance verification history for the current practice."""
    practice_id = _ensure_practice(current_user)

    filters = [InsuranceVerification.practice_id == practice_id]

    if patient_id:
        filters.append(InsuranceVerification.patient_id == patient_id)

    # Total count
    count_query = select(func.count(InsuranceVerification.id)).where(*filters)
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Paginated results ordered by most recent first
    query = (
        select(InsuranceVerification)
        .where(*filters)
        .order_by(InsuranceVerification.verified_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    verifications = result.scalars().all()

    items = []
    for v in verifications:
        resp = InsuranceVerificationResponse.model_validate(v)
        resp.message = _build_message(v)
        items.append(resp)

    return InsuranceVerificationListResponse(
        verifications=items,
        total=total,
    )


# ---------------------------------------------------------------------------
# Get single verification (GET /{verification_id})
# ---------------------------------------------------------------------------


@router.get("/{verification_id}", response_model=InsuranceVerificationResponse)
async def get_verification(
    verification_id: UUID,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Get a single insurance verification by ID, scoped to the current practice."""
    practice_id = _ensure_practice(current_user)

    result = await db.execute(
        select(InsuranceVerification).where(
            InsuranceVerification.id == verification_id,
            InsuranceVerification.practice_id == practice_id,
        )
    )
    verification = result.scalar_one_or_none()

    if not verification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Insurance verification not found",
        )

    response = InsuranceVerificationResponse.model_validate(verification)
    response.message = _build_message(verification)
    return response
