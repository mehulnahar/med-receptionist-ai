"""Practice configuration endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.practice_config import PracticeConfig
from app.schemas.practice_config import PracticeConfigResponse, PracticeConfigUpdate
from app.middleware.auth import get_current_user, require_practice_admin, require_any_staff

router = APIRouter()


@router.get("/", response_model=PracticeConfigResponse)
async def get_practice_config(
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Get the configuration for the current user's practice."""
    if not current_user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )

    result = await db.execute(
        select(PracticeConfig).where(
            PracticeConfig.practice_id == current_user.practice_id
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Practice configuration not found",
        )

    return PracticeConfigResponse.model_validate(config)


@router.put("/", response_model=PracticeConfigResponse)
async def update_practice_config(
    request: PracticeConfigUpdate,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update the configuration for the current user's practice (practice admin only)."""
    result = await db.execute(
        select(PracticeConfig).where(
            PracticeConfig.practice_id == current_user.practice_id
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Practice configuration not found",
        )

    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(config, field, value)

    await db.commit()
    await db.refresh(config)
    return PracticeConfigResponse.model_validate(config)
