"""Schedule management endpoints — weekly templates, overrides, and availability."""

from datetime import date, datetime, time, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.schedule import ScheduleTemplate, ScheduleOverride
from app.models.practice_config import PracticeConfig
from app.models.appointment import Appointment
from app.schemas.schedule import (
    ScheduleTemplateResponse,
    ScheduleTemplateUpdate,
    ScheduleOverrideResponse,
    ScheduleOverrideCreate,
    ScheduleOverrideListResponse,
    AvailableSlot,
    AvailabilityResponse,
)
from app.schemas.common import MessageResponse
from app.middleware.auth import get_current_user, require_practice_admin, require_any_staff

router = APIRouter()


# ---------------------------------------------------------------------------
# Weekly schedule template
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[ScheduleTemplateResponse])
async def get_weekly_schedule(
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Get the weekly schedule template (7 days) for the current practice."""
    if not current_user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )

    result = await db.execute(
        select(ScheduleTemplate)
        .where(ScheduleTemplate.practice_id == current_user.practice_id)
        .order_by(ScheduleTemplate.day_of_week)
    )
    templates = result.scalars().all()
    return [ScheduleTemplateResponse.model_validate(t) for t in templates]


@router.put("/", response_model=list[ScheduleTemplateResponse])
async def update_weekly_schedule(
    schedules: list[ScheduleTemplateUpdate],
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update the weekly schedule template. Accepts a list of day updates."""
    if not current_user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )

    updated: list[ScheduleTemplate] = []

    for schedule_update in schedules:
        result = await db.execute(
            select(ScheduleTemplate).where(
                ScheduleTemplate.practice_id == current_user.practice_id,
                ScheduleTemplate.day_of_week == schedule_update.day_of_week,
            )
        )
        template = result.scalar_one_or_none()

        if not template:
            # Create if it doesn't exist yet
            template = ScheduleTemplate(
                practice_id=current_user.practice_id,
                day_of_week=schedule_update.day_of_week,
            )
            db.add(template)

        update_data = schedule_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(template, field, value)

        updated.append(template)

    await db.commit()
    for t in updated:
        await db.refresh(t)

    return [ScheduleTemplateResponse.model_validate(t) for t in updated]


# ---------------------------------------------------------------------------
# Schedule overrides
# ---------------------------------------------------------------------------


@router.get("/overrides", response_model=ScheduleOverrideListResponse)
async def list_schedule_overrides(
    from_date: date | None = Query(None, description="Filter overrides from this date"),
    to_date: date | None = Query(None, description="Filter overrides up to this date"),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """List schedule overrides for the current practice with optional date range."""
    if not current_user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )

    query = select(ScheduleOverride).where(
        ScheduleOverride.practice_id == current_user.practice_id
    )

    if from_date:
        query = query.where(ScheduleOverride.date >= from_date)
    if to_date:
        query = query.where(ScheduleOverride.date <= to_date)

    query = query.order_by(ScheduleOverride.date)
    result = await db.execute(query)
    overrides = result.scalars().all()

    return ScheduleOverrideListResponse(
        overrides=[ScheduleOverrideResponse.model_validate(o) for o in overrides],
        total=len(overrides),
    )


@router.post("/overrides", response_model=ScheduleOverrideResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule_override(
    request: ScheduleOverrideCreate,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a schedule override (holiday, special hours, etc.). Practice admin only."""
    if not current_user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )

    # Check if an override already exists for this date
    existing = await db.execute(
        select(ScheduleOverride).where(
            ScheduleOverride.practice_id == current_user.practice_id,
            ScheduleOverride.date == request.date,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An override already exists for {request.date}",
        )

    override_data = request.model_dump()
    override = ScheduleOverride(
        **override_data,
        practice_id=current_user.practice_id,
        created_by=current_user.id,
    )
    db.add(override)
    await db.commit()
    await db.refresh(override)
    return ScheduleOverrideResponse.model_validate(override)


@router.delete("/overrides/{override_id}", response_model=MessageResponse)
async def delete_schedule_override(
    override_id: UUID,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a schedule override. Practice admin only."""
    result = await db.execute(
        select(ScheduleOverride).where(
            ScheduleOverride.id == override_id,
            ScheduleOverride.practice_id == current_user.practice_id,
        )
    )
    override = result.scalar_one_or_none()

    if not override:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Schedule override not found",
        )

    await db.delete(override)
    await db.commit()
    return MessageResponse(message="Schedule override deleted")


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


@router.get("/availability", response_model=AvailabilityResponse)
async def get_availability(
    date: date = Query(..., description="Date to check availability (YYYY-MM-DD)"),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Get available appointment slots for a specific date."""
    if not current_user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )

    practice_id = current_user.practice_id

    # ------------------------------------------------------------------
    # 1. Check for a schedule override on this date
    # ------------------------------------------------------------------
    override_result = await db.execute(
        select(ScheduleOverride).where(
            ScheduleOverride.practice_id == practice_id,
            ScheduleOverride.date == date,
        )
    )
    override = override_result.scalar_one_or_none()

    if override:
        if not override.is_working:
            # Not a working day — return empty
            return AvailabilityResponse(
                date=date,
                is_working_day=False,
                slots=[],
            )
        # Working override — use its hours
        start_time = override.start_time
        end_time = override.end_time
    else:
        # ------------------------------------------------------------------
        # 2. Fall back to the schedule template for this weekday
        # ------------------------------------------------------------------
        day_of_week = date.weekday()  # 0=Monday, 6=Sunday
        template_result = await db.execute(
            select(ScheduleTemplate).where(
                ScheduleTemplate.practice_id == practice_id,
                ScheduleTemplate.day_of_week == day_of_week,
            )
        )
        template = template_result.scalar_one_or_none()

        if not template or not template.is_enabled:
            return AvailabilityResponse(
                date=date,
                is_working_day=False,
                slots=[],
            )

        start_time = template.start_time
        end_time = template.end_time

    # Guard: if times are missing even though it should be a working day
    if not start_time or not end_time:
        return AvailabilityResponse(
            date=date,
            is_working_day=False,
            slots=[],
        )

    # ------------------------------------------------------------------
    # 3. Get practice config for slot duration and overbooking settings
    # ------------------------------------------------------------------
    config_result = await db.execute(
        select(PracticeConfig).where(PracticeConfig.practice_id == practice_id)
    )
    config = config_result.scalar_one_or_none()

    slot_duration = config.slot_duration_minutes if config else 15
    allow_overbooking = config.allow_overbooking if config else False
    max_overbooking = config.max_overbooking_per_slot if config else 2

    # ------------------------------------------------------------------
    # 4. Generate all time slots
    # ------------------------------------------------------------------
    slots_times: list[time] = []
    current = datetime.combine(date, start_time)
    end_dt = datetime.combine(date, end_time)
    slot_delta = timedelta(minutes=slot_duration)

    while current + slot_delta <= end_dt:
        slots_times.append(current.time())
        current += slot_delta

    # ------------------------------------------------------------------
    # 5. Query existing appointments for this date
    # ------------------------------------------------------------------
    appt_result = await db.execute(
        select(Appointment.time, func.count(Appointment.id))
        .where(
            Appointment.practice_id == practice_id,
            Appointment.date == date,
            Appointment.status.notin_(["cancelled"]),
        )
        .group_by(Appointment.time)
    )
    booked_counts: dict[time, int] = {row[0]: row[1] for row in appt_result.all()}

    # ------------------------------------------------------------------
    # 6. Build availability slots
    # ------------------------------------------------------------------
    available_slots: list[AvailableSlot] = []
    for slot_time in slots_times:
        booked = booked_counts.get(slot_time, 0)
        if allow_overbooking:
            is_available = booked < max_overbooking
        else:
            is_available = booked == 0

        available_slots.append(
            AvailableSlot(
                time=slot_time,
                is_available=is_available,
                current_bookings=booked,
            )
        )

    return AvailabilityResponse(
        date=date,
        is_working_day=True,
        slots=available_slots,
    )
