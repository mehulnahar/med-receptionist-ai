"""Appointment type CRUD endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.appointment_type import AppointmentType
from app.schemas.appointment_type import (
    AppointmentTypeCreate,
    AppointmentTypeUpdate,
    AppointmentTypeResponse,
    AppointmentTypeListResponse,
)
from app.schemas.common import MessageResponse
from app.middleware.auth import get_current_user, require_practice_admin, require_any_staff

router = APIRouter()


@router.get("/", response_model=AppointmentTypeListResponse)
async def list_appointment_types(
    include_inactive: bool = Query(False, description="Include deactivated types (admin use)"),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """List all appointment types for the current practice."""
    if not current_user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )

    query = (
        select(AppointmentType)
        .where(AppointmentType.practice_id == current_user.practice_id)
    )
    if not include_inactive:
        query = query.where(AppointmentType.is_active == True)  # noqa: E712
    query = query.order_by(AppointmentType.sort_order, AppointmentType.name)

    result = await db.execute(query)
    types = result.scalars().all()

    return AppointmentTypeListResponse(
        appointment_types=[AppointmentTypeResponse.model_validate(t) for t in types],
        total=len(types),
    )


@router.post("/", response_model=AppointmentTypeResponse, status_code=status.HTTP_201_CREATED)
async def create_appointment_type(
    request: AppointmentTypeCreate,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new appointment type. Practice admin only."""
    if not current_user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )

    type_data = request.model_dump()
    appointment_type = AppointmentType(
        **type_data,
        practice_id=current_user.practice_id,
    )
    db.add(appointment_type)
    await db.commit()
    await db.refresh(appointment_type)
    return AppointmentTypeResponse.model_validate(appointment_type)


@router.put("/{type_id}", response_model=AppointmentTypeResponse)
async def update_appointment_type(
    type_id: UUID,
    request: AppointmentTypeUpdate,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update an appointment type. Practice admin only."""
    result = await db.execute(
        select(AppointmentType).where(
            AppointmentType.id == type_id,
            AppointmentType.practice_id == current_user.practice_id,
        )
    )
    appointment_type = result.scalar_one_or_none()

    if not appointment_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment type not found in your practice",
        )

    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(appointment_type, field, value)

    await db.commit()
    await db.refresh(appointment_type)
    return AppointmentTypeResponse.model_validate(appointment_type)


@router.delete("/{type_id}", response_model=MessageResponse)
async def deactivate_appointment_type(
    type_id: UUID,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate an appointment type (soft delete). Practice admin only."""
    result = await db.execute(
        select(AppointmentType).where(
            AppointmentType.id == type_id,
            AppointmentType.practice_id == current_user.practice_id,
        )
    )
    appointment_type = result.scalar_one_or_none()

    if not appointment_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment type not found in your practice",
        )

    appointment_type.is_active = False
    await db.commit()
    return MessageResponse(message=f"Appointment type '{appointment_type.name}' deactivated")
