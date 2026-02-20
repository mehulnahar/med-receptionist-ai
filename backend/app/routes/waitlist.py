"""
Waitlist management API endpoints.

Provides endpoints for:
- Listing waitlist entries (with filters)
- Adding entries to the waitlist
- Updating entry status/priority/notes
- Removing entries from the waitlist
- Viewing waitlist stats
"""

import logging
from datetime import date, time, datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, desc, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.waitlist import WaitlistEntry
from app.middleware.auth import require_any_staff, require_practice_admin
from app.services.waitlist_service import (
    add_to_waitlist,
    get_waitlist_stats,
    expire_old_entries,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class WaitlistEntryResponse(BaseModel):
    id: UUID
    practice_id: UUID
    patient_id: UUID | None = None
    patient_name: str
    patient_phone: str
    appointment_type_id: UUID | None = None
    preferred_date_start: date | None = None
    preferred_date_end: date | None = None
    preferred_time_start: time | None = None
    preferred_time_end: time | None = None
    notes: str | None = None
    priority: int
    status: str
    notified_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class _DateTimeRangeValidator:
    """Mixin for cross-field date/time range validation."""

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.preferred_date_start and self.preferred_date_end:
            if self.preferred_date_start > self.preferred_date_end:
                raise ValueError("preferred_date_start cannot be after preferred_date_end")
        if self.preferred_time_start and self.preferred_time_end:
            if self.preferred_time_start > self.preferred_time_end:
                raise ValueError("preferred_time_start cannot be after preferred_time_end")
        return self


class AddWaitlistRequest(_DateTimeRangeValidator, BaseModel):
    patient_name: str = Field(..., min_length=1, max_length=255)
    patient_phone: str = Field(..., min_length=1, max_length=20, pattern=r"^\+[1-9]\d{1,14}$")
    patient_id: UUID | None = None
    appointment_type_id: UUID | None = None
    preferred_date_start: date | None = None
    preferred_date_end: date | None = None
    preferred_time_start: time | None = None
    preferred_time_end: time | None = None
    notes: str | None = Field(None, max_length=2000)
    priority: int = Field(default=3, ge=1, le=5)


class UpdateWaitlistRequest(_DateTimeRangeValidator, BaseModel):
    status: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(None, max_length=2000)
    preferred_date_start: date | None = None
    preferred_date_end: date | None = None
    preferred_time_start: time | None = None
    preferred_time_end: time | None = None


class WaitlistListResponse(BaseModel):
    entries: list[WaitlistEntryResponse]
    total: int


class WaitlistStatsResponse(BaseModel):
    total_waiting: int
    total_notified: int
    total_booked: int
    total_expired: int
    total_cancelled: int
    avg_wait_hours: float | None = None
    conversion_rate: float


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


VALID_STATUSES = {"waiting", "notified", "booked", "expired", "cancelled"}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=WaitlistStatsResponse)
async def waitlist_stats(
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Get waitlist statistics for the current practice."""
    practice_id = _ensure_practice(current_user)

    # Expire old entries first to keep stats accurate
    await expire_old_entries(db)

    stats = await get_waitlist_stats(db, practice_id)
    return WaitlistStatsResponse(**stats)


@router.get("/", response_model=WaitlistListResponse)
async def list_waitlist_entries(
    status_filter: Optional[str] = Query(None, alias="status"),
    patient_name: Optional[str] = Query(None, description="Filter by patient name (partial match)"),
    date_from: Optional[str] = Query(None, description="Filter entries created from this date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter entries created up to this date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """List waitlist entries for the current practice, with optional filters."""
    practice_id = _ensure_practice(current_user)

    filters = [WaitlistEntry.practice_id == practice_id]

    if status_filter:
        if status_filter not in VALID_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
            )
        filters.append(WaitlistEntry.status == status_filter)

    if patient_name:
        safe_name = patient_name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(WaitlistEntry.patient_name.ilike(f"%{safe_name}%"))

    dt_from_val = None
    dt_to_val = None

    if date_from:
        try:
            dt_from_val = date.fromisoformat(date_from)
            filters.append(
                WaitlistEntry.created_at >= datetime(
                    dt_from_val.year, dt_from_val.month, dt_from_val.day, tzinfo=timezone.utc
                )
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format. Use YYYY-MM-DD.")

    if date_to:
        try:
            from datetime import timedelta
            dt_to_val = date.fromisoformat(date_to)
            filters.append(
                WaitlistEntry.created_at < datetime(
                    dt_to_val.year, dt_to_val.month, dt_to_val.day, tzinfo=timezone.utc
                ) + timedelta(days=1)
            )
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
        select(func.count(WaitlistEntry.id)).where(and_(*filters))
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(WaitlistEntry)
        .where(and_(*filters))
        .order_by(WaitlistEntry.priority.asc(), desc(WaitlistEntry.created_at))
        .limit(limit)
        .offset(offset)
    )

    return WaitlistListResponse(
        entries=[WaitlistEntryResponse.model_validate(r) for r in result.scalars().all()],
        total=total,
    )


@router.post("/", response_model=WaitlistEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_waitlist_entry(
    request: AddWaitlistRequest,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Add a new entry to the waitlist (manual add from dashboard)."""
    practice_id = _ensure_practice(current_user)

    entry = await add_to_waitlist(
        db=db,
        practice_id=practice_id,
        patient_name=request.patient_name,
        patient_phone=request.patient_phone,
        patient_id=request.patient_id,
        appointment_type_id=request.appointment_type_id,
        preferred_date_start=request.preferred_date_start,
        preferred_date_end=request.preferred_date_end,
        preferred_time_start=request.preferred_time_start,
        preferred_time_end=request.preferred_time_end,
        notes=request.notes,
        priority=request.priority,
    )

    return WaitlistEntryResponse.model_validate(entry)


@router.patch("/{entry_id}", response_model=WaitlistEntryResponse)
async def update_waitlist_entry(
    entry_id: UUID,
    request: UpdateWaitlistRequest,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Update a waitlist entry (status, priority, notes, date preferences)."""
    practice_id = _ensure_practice(current_user)

    result = await db.execute(
        select(WaitlistEntry).where(
            and_(
                WaitlistEntry.id == entry_id,
                WaitlistEntry.practice_id == practice_id,
            )
        )
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")

    # Use exclude_unset so we can distinguish "field omitted" from "field = null"
    # This allows callers to explicitly clear optional fields by sending null.
    update_data = request.model_dump(exclude_unset=True)

    if "status" in update_data:
        if update_data["status"] not in VALID_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
            )

    UPDATABLE_FIELDS = {
        "status", "priority", "notes",
        "preferred_date_start", "preferred_date_end",
        "preferred_time_start", "preferred_time_end",
    }
    for field, value in update_data.items():
        if field in UPDATABLE_FIELDS:
            setattr(entry, field, value)

    await db.flush()
    await db.commit()
    await db.refresh(entry)

    return WaitlistEntryResponse.model_validate(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_waitlist_entry(
    entry_id: UUID,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Remove an entry from the waitlist."""
    practice_id = _ensure_practice(current_user)

    result = await db.execute(
        select(WaitlistEntry).where(
            and_(
                WaitlistEntry.id == entry_id,
                WaitlistEntry.practice_id == practice_id,
            )
        )
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")

    await db.delete(entry)
    await db.flush()
    await db.commit()
