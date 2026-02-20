"""Practice configuration endpoints."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.practice_config import PracticeConfig
from app.schemas.practice_config import PracticeConfigResponse, PracticeConfigUpdate
from app.middleware.auth import get_current_user, require_practice_admin, require_any_staff
from app.utils.cache import practice_config_cache

logger = logging.getLogger(__name__)
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

    # Track if transfer_number is changing
    transfer_number_changed = (
        "transfer_number" in update_data
        and update_data["transfer_number"] != config.transfer_number
    )

    for field, value in update_data.items():
        setattr(config, field, value)

    # Invalidate cache BEFORE commit — prevents a race where another request
    # reads the old DB row and re-populates the cache between commit and invalidate
    practice_config_cache.invalidate(f"practice_config:{current_user.practice_id}")

    await db.commit()
    await db.refresh(config)

    # Sync transfer number to Vapi assistant when it changes
    if transfer_number_changed and config.vapi_assistant_id:
        try:
            from app.services.vapi_service import update_assistant_transfer_number
            await update_assistant_transfer_number(
                assistant_id=config.vapi_assistant_id,
                transfer_number=config.transfer_number,
            )
        except Exception as e:
            logger.warning("Failed to sync transfer number to Vapi: %s", e)

    return PracticeConfigResponse.model_validate(config)
