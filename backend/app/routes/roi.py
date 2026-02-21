"""
ROI Dashboard API routes — the key selling feature for practices.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_practice_admin
from app.models.user import User
from app.commercial.roi_service import get_roi_summary, get_roi_trends

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/roi", tags=["ROI Dashboard"])


@router.get("/summary")
async def roi_summary(
    period: str = Query("month", pattern="^(week|month)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Get ROI summary metrics for the current practice."""
    practice_id = current_user.practice_id
    if not practice_id:
        return {"error": "No practice associated"}

    return await get_roi_summary(db, practice_id, period)


@router.get("/trends")
async def roi_trends(
    weeks: int = Query(8, ge=1, le=52),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Get weekly trend data for ROI charts."""
    practice_id = current_user.practice_id
    if not practice_id:
        return {"error": "No practice associated"}

    return await get_roi_trends(db, practice_id, weeks)
