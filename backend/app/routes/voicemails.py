"""
Voicemail management API endpoints.

Provides endpoints for:
- Listing voicemails with status filtering
- Updating voicemail status (mark read, responded, archived)
- Getting unread voicemail count (for dashboard badge)
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.voicemail import Voicemail
from app.middleware.auth import require_any_staff

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class VoicemailResponse(BaseModel):
    id: UUID
    practice_id: UUID
    call_id: UUID | None = None
    patient_id: UUID | None = None
    caller_name: str | None = None
    caller_phone: str | None = None
    message: str
    urgency: str = "normal"
    callback_requested: bool = True
    preferred_callback_time: str | None = None
    reason: str | None = None
    status: str = "new"
    responded_by: UUID | None = None
    responded_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class VoicemailStatusUpdate(BaseModel):
    status: str  # new, read, responded, archived


class VoicemailCountResponse(BaseModel):
    unread: int


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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[VoicemailResponse])
async def list_voicemails(
    status_filter: str = Query("new", alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """List voicemails for the practice, filterable by status."""
    practice_id = _ensure_practice(current_user)

    filters = [Voicemail.practice_id == practice_id]
    if status_filter != "all":
        filters.append(Voicemail.status == status_filter)

    result = await db.execute(
        select(Voicemail)
        .where(*filters)
        .order_by(desc(Voicemail.created_at))
        .offset(offset)
        .limit(limit)
    )

    return [VoicemailResponse.model_validate(vm) for vm in result.scalars().all()]


@router.patch("/{voicemail_id}/status", response_model=VoicemailResponse)
async def update_voicemail_status(
    voicemail_id: UUID,
    body: VoicemailStatusUpdate,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Update a voicemail's status (mark read, responded, archived)."""
    practice_id = _ensure_practice(current_user)

    valid_statuses = {"new", "read", "responded", "archived"}
    if body.status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(valid_statuses))}",
        )

    result = await db.execute(
        select(Voicemail).where(
            Voicemail.id == voicemail_id,
            Voicemail.practice_id == practice_id,
        )
    )
    voicemail = result.scalar_one_or_none()

    if not voicemail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voicemail not found",
        )

    voicemail.status = body.status

    # Track who responded and when
    if body.status == "responded":
        voicemail.responded_by = current_user.id
        voicemail.responded_at = datetime.now(timezone.utc)

    await db.flush()

    return VoicemailResponse.model_validate(voicemail)


@router.get("/count", response_model=VoicemailCountResponse)
async def get_voicemail_count(
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Get count of unread (new) voicemails for dashboard badge."""
    practice_id = _ensure_practice(current_user)

    result = await db.execute(
        select(func.count(Voicemail.id)).where(
            Voicemail.practice_id == practice_id,
            Voicemail.status == "new",
        )
    )
    count = result.scalar() or 0

    return VoicemailCountResponse(unread=count)
