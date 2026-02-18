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
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, and_
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


class AddWaitlistRequest(BaseModel):
    patient_name: str = Field(..., min_length=1, max_length=255)
    patient_phone: str = Field(..., min_length=1, max_length=20)
    patient_id: UUID | None = None
    appointment_type_id: UUID | None = None
    preferred_date_start: date | None = None
    preferred_date_end: date | None = None
    preferred_time_start: time | None = None
    preferred_time_end: time | None = None
    notes: str | None = None
    priority: int = Field(default=3, ge=1, le=5)


class UpdateWaitlistRequest(BaseModel):
    status: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = None
    preferred_date_start: date | None = None
    preferred_date_end: date | None = None
    preferred_time_start: time | None = None
    preferred_time_end: time | None = None


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


@router.get("/", response_model=list[WaitlistEntryResponse])
async def list_waitlist_entries(
    status_filter: Optional[str] = Query(None, alias="status"),
    patient_name: Optional[str] = Query(None, description="Filter by patient name (partial match)"),
    date_from: Optional[str] = Query(None, description="Filter entries created from this date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter entries created up to this date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=200),
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
        filters.append(WaitlistEntry.patient_name.ilike(f"%{patient_name}%"))

    if date_from:
        try:
            dt_from = date.fromisoformat(date_from)
            filters.append(
                WaitlistEntry.created_at >= datetime(
                    dt_from.year, dt_from.month, dt_from.day, tzinfo=timezone.utc
                )
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format. Use YYYY-MM-DD.")

    if date_to:
        try:
            from datetime import timedelta
            dt_to = date.fromisoformat(date_to)
            filters.append(
                WaitlistEntry.created_at < datetime(
                    dt_to.year, dt_to.month, dt_to.day, tzinfo=timezone.utc
                ) + timedelta(days=1)
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format. Use YYYY-MM-DD.")

    result = await db.execute(
        select(WaitlistEntry)
        .where(and_(*filters))
        .order_by(WaitlistEntry.priority.asc(), desc(WaitlistEntry.created_at))
        .limit(limit)
        .offset(offset)
    )

    return [WaitlistEntryResponse.model_validate(r) for r in result.scalars().all()]


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

    if request.status is not None:
        if request.status not in VALID_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
            )
        entry.status = request.status

    if request.priority is not None:
        entry.priority = request.priority

    if request.notes is not None:
        entry.notes = request.notes

    if request.preferred_date_start is not None:
        entry.preferred_date_start = request.preferred_date_start

    if request.preferred_date_end is not None:
        entry.preferred_date_end = request.preferred_date_end

    if request.preferred_time_start is not None:
        entry.preferred_time_start = request.preferred_time_start

    if request.preferred_time_end is not None:
        entry.preferred_time_end = request.preferred_time_end

    await db.flush()

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
