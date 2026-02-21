"""
Survey API routes — post-visit satisfaction surveys and Google review prompts.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_practice_admin
from app.models.user import User
from app.scale.survey_service import (
    get_survey_stats,
    process_survey_response,
    send_post_visit_survey,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/surveys", tags=["Surveys"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SendSurveyRequest(BaseModel):
    appointment_id: str


class SurveyResponseRequest(BaseModel):
    token: str
    rating: int = Field(..., ge=1, le=5)
    feedback: str = Field("", max_length=2000)


class SurveyConfigUpdate(BaseModel):
    enabled: bool | None = None
    delay_hours: int | None = Field(None, ge=0, le=72)
    include_google_review: bool | None = None
    google_review_url: str | None = Field(None, max_length=500)
    min_rating_for_review: int | None = Field(None, ge=1, le=5)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/stats")
async def survey_stats(
    period: str = Query("month", pattern="^(week|month)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Get survey statistics for the practice."""
    if not current_user.practice_id:
        return {"error": "No practice associated"}
    return await get_survey_stats(db, str(current_user.practice_id), period)


@router.post("/send")
async def send_survey(
    body: SendSurveyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Manually trigger a survey for a specific appointment."""
    result = await send_post_visit_survey(db, body.appointment_id)
    if not result:
        raise HTTPException(status_code=400, detail="Could not send survey")
    return result


@router.post("/respond")
async def respond_to_survey(
    body: SurveyResponseRequest,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint for patients to submit survey responses."""
    result = await process_survey_response(
        db, body.token, body.rating, body.feedback
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/config")
async def get_survey_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Get survey configuration for the practice."""
    from app.scale.survey_service import _get_survey_config, DEFAULT_SURVEY_CONFIG

    if not current_user.practice_id:
        return DEFAULT_SURVEY_CONFIG

    result = await db.execute(
        text("SELECT config FROM practices WHERE id = :pid"),
        {"pid": str(current_user.practice_id)},
    )
    row = result.fetchone()
    practice_config = row.config if row and row.config else {}
    return _get_survey_config(practice_config)


@router.put("/config")
async def update_survey_config(
    body: SurveyConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Update survey configuration."""
    if not current_user.practice_id:
        raise HTTPException(status_code=400, detail="No practice associated")

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Update the survey sub-key within practice config JSONB
    for key, value in update_data.items():
        await db.execute(
            text("""
                UPDATE practices
                SET config = jsonb_set(
                    COALESCE(config, '{}'::jsonb),
                    :path,
                    :value::jsonb,
                    true
                )
                WHERE id = :pid
            """),
            {
                "pid": str(current_user.practice_id),
                "path": f"{{survey,{key}}}",
                "value": (
                    f'"{value}"' if isinstance(value, str) else str(value).lower()
                ),
            },
        )
    await db.commit()

    return {"success": True, "updated_fields": list(update_data.keys())}


@router.get("/")
async def list_surveys(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """List recent surveys with pagination."""
    if not current_user.practice_id:
        return {"surveys": [], "total": 0}

    pid = str(current_user.practice_id)

    count_result = await db.execute(
        text("SELECT COUNT(*) FROM surveys WHERE practice_id = :pid"),
        {"pid": pid},
    )
    total = count_result.scalar_one()

    result = await db.execute(
        text("""
            SELECT id, appointment_id, patient_phone, rating, feedback,
                   status, created_at, responded_at
            FROM surveys
            WHERE practice_id = :pid
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"pid": pid, "limit": limit, "offset": offset},
    )

    surveys = [
        {
            "id": str(row.id),
            "appointment_id": str(row.appointment_id),
            "patient_phone": row.patient_phone,
            "rating": row.rating,
            "feedback": row.feedback,
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "responded_at": row.responded_at.isoformat() if row.responded_at else None,
        }
        for row in result.fetchall()
    ]

    return {"surveys": surveys, "total": total}
