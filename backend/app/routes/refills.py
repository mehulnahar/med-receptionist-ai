"""
Prescription refill request API endpoints.

Provides endpoints for:
- Listing refill requests (with filters)
- Updating refill request status (approve, deny, complete)
"""

import logging
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.refill_request import RefillRequest
from app.middleware.auth import require_any_staff

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RefillResponse(BaseModel):
    id: UUID
    practice_id: UUID
    patient_id: UUID | None = None
    call_id: UUID | None = None
    medication_name: str
    dosage: str | None = None
    pharmacy_name: str | None = None
    pharmacy_phone: str | None = None
    prescribing_doctor: str | None = None
    caller_name: str | None = None
    caller_phone: str | None = None
    urgency: str | None = None
    notes: str | None = None
    status: str | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class RefillListResponse(BaseModel):
    refills: list[RefillResponse]
    total: int


class UpdateStatusRequest(BaseModel):
    status: Literal["pending", "in_review", "approved", "denied", "completed"]
    notes: str | None = Field(None, max_length=2000)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_practice(user: User) -> UUID:
    if not user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )
    return user.practice_id


VALID_STATUSES = {"pending", "in_review", "approved", "denied", "completed"}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/", response_model=RefillListResponse)
async def list_refill_requests(
    status_filter: Optional[str] = Query(None, alias="status"),
    date_from: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """List refill requests for the current practice, with optional filters."""
    practice_id = _ensure_practice(current_user)

    filters = [RefillRequest.practice_id == practice_id]

    if status_filter:
        if status_filter not in VALID_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
            )
        filters.append(RefillRequest.status == status_filter)

    dt_from_val = None
    dt_to_val = None

    if date_from:
        try:
            from datetime import date as date_type
            dt_from_val = date_type.fromisoformat(date_from)
            filters.append(RefillRequest.created_at >= datetime(dt_from_val.year, dt_from_val.month, dt_from_val.day, tzinfo=timezone.utc))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format. Use YYYY-MM-DD.")

    if date_to:
        try:
            from datetime import date as date_type, timedelta
            dt_to_val = date_type.fromisoformat(date_to)
            # Include the entire end date
            filters.append(RefillRequest.created_at < datetime(dt_to_val.year, dt_to_val.month, dt_to_val.day, tzinfo=timezone.utc) + timedelta(days=1))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format. Use YYYY-MM-DD.")

    # Validate date ordering and cap range
    if dt_from_val and dt_to_val:
        if dt_from_val > dt_to_val:
            raise HTTPException(status_code=400, detail="date_from cannot be after date_to.")
        if (dt_to_val - dt_from_val).days > 365:
            raise HTTPException(status_code=400, detail="Date range cannot exceed 365 days.")

    # Total count for pagination
    count_result = await db.execute(
        select(func.count(RefillRequest.id)).where(and_(*filters))
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(RefillRequest)
        .where(and_(*filters))
        .order_by(desc(RefillRequest.created_at))
        .limit(limit)
        .offset(offset)
    )

    return RefillListResponse(
        refills=[RefillResponse.model_validate(r) for r in result.scalars().all()],
        total=total,
    )


@router.patch("/{refill_id}/status", response_model=RefillResponse)
async def update_refill_status(
    refill_id: UUID,
    request: UpdateStatusRequest,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Update the status of a refill request (approve, deny, complete, etc.)."""
    practice_id = _ensure_practice(current_user)

    if request.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )

    result = await db.execute(
        select(RefillRequest).where(
            and_(
                RefillRequest.id == refill_id,
                RefillRequest.practice_id == practice_id,
            )
        )
    )
    refill = result.scalar_one_or_none()

    if not refill:
        raise HTTPException(status_code=404, detail="Refill request not found")

    refill.status = request.status

    # Only set review attribution for actual review actions
    REVIEW_STATUSES = {"approved", "denied", "completed"}
    if request.status in REVIEW_STATUSES:
        refill.reviewed_by = current_user.id
        refill.reviewed_at = datetime.now(timezone.utc)
    elif request.status == "pending":
        # Re-opening clears the review attribution
        refill.reviewed_by = None
        refill.reviewed_at = None

    if request.notes is not None:
        refill.notes = request.notes

    await db.flush()
    await db.commit()
    await db.refresh(refill)

    return RefillResponse.model_validate(refill)
