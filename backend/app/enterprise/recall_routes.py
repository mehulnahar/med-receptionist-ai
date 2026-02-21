"""
Outbound recall campaign API routes.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import require_practice_admin
from app.models.user import User
from app.enterprise.recall_service import RecallService, RECALL_TYPES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/recall", tags=["Recall Campaigns"])


class CreateCampaignRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    recall_type: str
    params: dict = {}


class ScheduleCampaignRequest(BaseModel):
    run_at: str  # ISO datetime string


class RecallResponseRequest(BaseModel):
    phone: str
    response: str


@router.get("/campaigns")
async def list_campaigns(
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """List recall campaigns."""
    if not current_user.practice_id:
        return {"campaigns": []}
    campaigns = await RecallService.list_campaigns(
        db, str(current_user.practice_id), status
    )
    return {"campaigns": campaigns}


@router.post("/campaigns", status_code=201)
async def create_campaign(
    body: CreateCampaignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Create a new recall campaign."""
    if not current_user.practice_id:
        raise HTTPException(status_code=400, detail="No practice associated")

    if body.recall_type not in RECALL_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid recall type. Valid: {', '.join(RECALL_TYPES.keys())}",
        )

    return await RecallService.create_campaign(
        db,
        practice_id=str(current_user.practice_id),
        name=body.name,
        recall_type=body.recall_type,
        params=body.params,
        created_by=str(current_user.id),
    )


@router.get("/campaigns/{campaign_id}")
async def get_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Get campaign detail with stats."""
    if not current_user.practice_id:
        raise HTTPException(status_code=400, detail="No practice associated")

    from sqlalchemy import text
    result = await db.execute(
        text("""
            SELECT id, name, recall_type, params, status,
                   scheduled_at, started_at, completed_at, created_at
            FROM recall_campaigns
            WHERE id = :cid AND practice_id = :pid
        """),
        {"cid": campaign_id, "pid": str(current_user.practice_id)},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Campaign not found")

    stats = await RecallService.get_campaign_stats(db, campaign_id)

    return {
        "id": str(row.id),
        "name": row.name,
        "recall_type": row.recall_type,
        "params": row.params,
        "status": row.status,
        "stats": stats,
        "scheduled_at": row.scheduled_at.isoformat() if row.scheduled_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.post("/campaigns/{campaign_id}/run")
async def run_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Manually run a campaign."""
    if not current_user.practice_id:
        raise HTTPException(status_code=400, detail="No practice associated")

    result = await RecallService.run_campaign(
        db, campaign_id, str(current_user.practice_id)
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/campaigns/{campaign_id}/schedule")
async def schedule_campaign(
    campaign_id: str,
    body: ScheduleCampaignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Schedule a campaign to run at a specific time."""
    if not current_user.practice_id:
        raise HTTPException(status_code=400, detail="No practice associated")

    try:
        run_at = datetime.fromisoformat(body.run_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format")

    from sqlalchemy import text
    await db.execute(
        text("""
            UPDATE recall_campaigns
            SET status = 'scheduled', scheduled_at = :run_at
            WHERE id = :cid AND practice_id = :pid AND status = 'draft'
        """),
        {
            "cid": campaign_id,
            "pid": str(current_user.practice_id),
            "run_at": run_at,
        },
    )
    await db.commit()
    return {"success": True, "scheduled_at": run_at.isoformat()}


@router.post("/campaigns/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Pause a running campaign."""
    from sqlalchemy import text
    result = await db.execute(
        text("""
            UPDATE recall_campaigns SET status = 'paused'
            WHERE id = :cid AND practice_id = :pid AND status = 'running'
        """),
        {"cid": campaign_id, "pid": str(current_user.practice_id)},
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=400, detail="Campaign not running")
    return {"success": True}


@router.get("/campaigns/{campaign_id}/contacts")
async def list_contacts(
    campaign_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """List contacted patients in a campaign."""
    from sqlalchemy import text
    result = await db.execute(
        text("""
            SELECT id, patient_name, patient_phone, last_visit_date,
                   status, sent_at, responded_at
            FROM recall_contacts
            WHERE campaign_id = :cid AND practice_id = :pid
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        {
            "cid": campaign_id,
            "pid": str(current_user.practice_id),
            "limit": limit,
        },
    )
    contacts = [
        {
            "id": str(row.id),
            "patient_name": row.patient_name,
            "patient_phone": row.patient_phone,
            "last_visit_date": row.last_visit_date.isoformat() if row.last_visit_date else None,
            "status": row.status,
            "sent_at": row.sent_at.isoformat() if row.sent_at else None,
            "responded_at": row.responded_at.isoformat() if row.responded_at else None,
        }
        for row in result.fetchall()
    ]
    return {"contacts": contacts}


@router.post("/response")
async def recall_response(
    body: RecallResponseRequest,
    db: AsyncSession = Depends(get_db),
):
    """Public webhook for SMS recall responses (no auth)."""
    result = await RecallService.process_recall_response(
        db, body.phone, body.response
    )
    return result
