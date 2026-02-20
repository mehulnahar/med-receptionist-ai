"""Insurance carrier CRUD endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.insurance_carrier import InsuranceCarrier
from app.schemas.insurance_carrier import (
    InsuranceCarrierCreate,
    InsuranceCarrierUpdate,
    InsuranceCarrierResponse,
    InsuranceCarrierListResponse,
)
from app.schemas.common import MessageResponse
from app.middleware.auth import get_current_user, require_practice_admin, require_any_staff

router = APIRouter()


@router.get("/", response_model=InsuranceCarrierListResponse)
async def list_insurance_carriers(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """List insurance carriers for the current practice (paginated)."""
    if not current_user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )

    base_filter = InsuranceCarrier.practice_id == current_user.practice_id

    total_result = await db.execute(
        select(func.count(InsuranceCarrier.id)).where(base_filter)
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(InsuranceCarrier)
        .where(base_filter)
        .order_by(InsuranceCarrier.name)
        .limit(limit)
        .offset(offset)
    )
    carriers = result.scalars().all()

    return InsuranceCarrierListResponse(
        carriers=[InsuranceCarrierResponse.model_validate(c) for c in carriers],
        total=total,
    )


@router.post("/", response_model=InsuranceCarrierResponse, status_code=status.HTTP_201_CREATED)
async def create_insurance_carrier(
    request: InsuranceCarrierCreate,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Add an insurance carrier. Practice admin only."""
    if not current_user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )

    # Check for duplicate carrier name within the practice
    existing = await db.execute(
        select(InsuranceCarrier).where(
            InsuranceCarrier.practice_id == current_user.practice_id,
            func.lower(InsuranceCarrier.name) == request.name.strip().lower(),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Insurance carrier '{request.name}' already exists in this practice",
        )

    carrier_data = request.model_dump()
    carrier = InsuranceCarrier(
        **carrier_data,
        practice_id=current_user.practice_id,
    )
    db.add(carrier)
    await db.commit()
    await db.refresh(carrier)
    return InsuranceCarrierResponse.model_validate(carrier)


@router.put("/{carrier_id}", response_model=InsuranceCarrierResponse)
async def update_insurance_carrier(
    carrier_id: UUID,
    request: InsuranceCarrierUpdate,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update an insurance carrier. Practice admin only."""
    result = await db.execute(
        select(InsuranceCarrier).where(
            InsuranceCarrier.id == carrier_id,
            InsuranceCarrier.practice_id == current_user.practice_id,
        )
    )
    carrier = result.scalar_one_or_none()

    if not carrier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Insurance carrier not found in your practice",
        )

    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(carrier, field, value)

    await db.commit()
    await db.refresh(carrier)
    return InsuranceCarrierResponse.model_validate(carrier)


@router.delete("/{carrier_id}", response_model=MessageResponse)
async def deactivate_insurance_carrier(
    carrier_id: UUID,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate an insurance carrier (soft delete). Practice admin only."""
    result = await db.execute(
        select(InsuranceCarrier).where(
            InsuranceCarrier.id == carrier_id,
            InsuranceCarrier.practice_id == current_user.practice_id,
        )
    )
    carrier = result.scalar_one_or_none()

    if not carrier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Insurance carrier not found in your practice",
        )

    carrier.is_active = False
    await db.commit()
    return MessageResponse(message=f"Insurance carrier '{carrier.name}' deactivated")
