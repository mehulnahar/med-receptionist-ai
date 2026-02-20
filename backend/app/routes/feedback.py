"""
Feedback loop API endpoints for the AI Medical Receptionist.

Provides endpoints for:
- Viewing call quality scores and trends
- Viewing auto-detected improvement insights
- Applying or dismissing insights
- Managing prompt versions
- Triggering manual pattern detection
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
from app.models.feedback import CallFeedback, PromptVersion, FeedbackInsight
from app.middleware.auth import require_practice_admin, require_any_staff
from app.services.feedback_service import (
    detect_patterns,
    generate_prompt_improvement,
    apply_prompt_improvement,
    push_prompt_to_vapi,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class FeedbackStatsResponse(BaseModel):
    """Aggregate feedback stats for the dashboard."""
    total_analyzed: int = 0
    avg_overall_score: float | None = None
    avg_resolution_score: float | None = None
    avg_empathy_score: float | None = None
    success_rate: float | None = None
    top_failure_points: list[dict] = []
    score_trend: list[dict] = []  # Last 7 days of avg scores
    calls_by_sentiment: dict = {}
    calls_by_intent: dict = {}


class InsightResponse(BaseModel):
    id: UUID
    insight_type: str
    category: str | None
    severity: str | None
    title: str
    description: str
    suggested_fix: str | None
    affected_calls: int
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class PromptVersionResponse(BaseModel):
    id: UUID
    version: int
    change_reason: str | None
    total_calls: int
    successful_calls: int
    avg_score: float | None
    booking_rate: float | None
    is_active: bool
    activated_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class ApplyInsightRequest(BaseModel):
    insight_ids: list[UUID] | None = None
    auto_push: bool = False  # If True, push to Vapi immediately


class ApplyPromptRequest(BaseModel):
    prompt_text: str
    change_reason: str
    push_to_vapi: bool = True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def _ensure_practice(user: User) -> UUID:
    if not user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )
    return user.practice_id


@router.get("/stats", response_model=FeedbackStatsResponse)
async def get_feedback_stats(
    days: int = Query(7, ge=1, le=90),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregate feedback statistics for the dashboard."""
    practice_id = _ensure_practice(current_user)
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    filters = [
        CallFeedback.practice_id == practice_id,
        CallFeedback.created_at >= cutoff,
    ]

    # Aggregate scores
    from sqlalchemy import Integer as SAInteger, cast as sa_cast
    agg = await db.execute(
        select(
            func.count(CallFeedback.id),
            func.avg(CallFeedback.overall_score),
            func.avg(CallFeedback.resolution_score),
            func.avg(CallFeedback.empathy_score),
            func.count(CallFeedback.id).filter(CallFeedback.was_successful == True),
        ).where(*filters)
    )
    row = agg.one()

    # Top failure points
    fp_result = await db.execute(
        select(
            CallFeedback.failure_point,
            func.count(CallFeedback.id).label("count"),
        )
        .where(*filters, CallFeedback.failure_point.isnot(None))
        .group_by(CallFeedback.failure_point)
        .order_by(desc("count"))
        .limit(5)
    )
    top_failures = [{"point": r[0], "count": r[1]} for r in fp_result.all()]

    # Daily score trend
    from sqlalchemy import cast, Date
    daily = await db.execute(
        select(
            cast(CallFeedback.created_at, Date).label("day"),
            func.avg(CallFeedback.overall_score).label("avg_score"),
            func.count(CallFeedback.id).label("count"),
        )
        .where(*filters)
        .group_by("day")
        .order_by("day")
    )
    score_trend = [
        {"date": str(r[0]), "avg_score": round(float(r[1]), 2) if r[1] else 0, "count": r[2]}
        for r in daily.all()
    ]

    return FeedbackStatsResponse(
        total_analyzed=row[0] or 0,
        avg_overall_score=round(float(row[1]), 2) if row[1] else None,
        avg_resolution_score=round(float(row[2]), 2) if row[2] else None,
        avg_empathy_score=round(float(row[3]), 2) if row[3] else None,
        success_rate=round((row[4] / row[0]) * 100, 1) if row[0] and row[0] > 0 else None,
        top_failure_points=top_failures,
        score_trend=score_trend,
    )


@router.get("/insights", response_model=list[InsightResponse])
async def list_insights(
    status_filter: str = Query("open", alias="status"),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """List feedback insights (auto-detected improvement suggestions). Practice admin only."""
    practice_id = _ensure_practice(current_user)

    filters = [FeedbackInsight.practice_id == practice_id]
    if status_filter != "all":
        filters.append(FeedbackInsight.status == status_filter)

    result = await db.execute(
        select(FeedbackInsight)
        .where(*filters)
        .order_by(desc(FeedbackInsight.created_at))
        .limit(limit)
    )

    return [InsightResponse.model_validate(i) for i in result.scalars().all()]


@router.post("/insights/detect")
async def trigger_pattern_detection(
    lookback_hours: int = Query(24, ge=1, le=168),
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger pattern detection on recent calls."""
    practice_id = _ensure_practice(current_user)

    insights = await detect_patterns(db, practice_id, lookback_hours)
    await db.commit()

    return {
        "status": "ok",
        "new_insights": len(insights),
        "insights": [{"title": i.title, "severity": i.severity} for i in insights],
    }


@router.post("/insights/{insight_id}/dismiss")
async def dismiss_insight(
    insight_id: UUID,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Dismiss an insight (mark as not actionable)."""
    practice_id = _ensure_practice(current_user)

    result = await db.execute(
        select(FeedbackInsight).where(
            FeedbackInsight.id == insight_id,
            FeedbackInsight.practice_id == practice_id,
        )
    )
    insight = result.scalar_one_or_none()
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")

    insight.status = "dismissed"
    await db.commit()

    return {"status": "ok"}


@router.post("/improve-prompt")
async def suggest_prompt_improvement(
    request: ApplyInsightRequest,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Generate an improved prompt based on feedback insights."""
    practice_id = _ensure_practice(current_user)

    suggestion = await generate_prompt_improvement(
        db, practice_id, request.insight_ids
    )

    if not suggestion:
        return {"status": "no_improvements", "message": "No actionable insights found or LLM unavailable"}

    # If auto_push, apply and push immediately
    if request.auto_push and suggestion.get("improved_prompt"):
        pv = await apply_prompt_improvement(
            db, practice_id,
            new_prompt=suggestion["improved_prompt"],
            change_reason="Auto-improvement: " + ", ".join(suggestion.get("changes_made", [])[:3]),
            change_diff="\n".join(suggestion.get("changes_made", [])),
        )
        pushed = await push_prompt_to_vapi(practice_id, suggestion["improved_prompt"], db)
        await db.commit()

        return {
            "status": "applied",
            "version": pv.version,
            "pushed_to_vapi": pushed,
            "changes": suggestion.get("changes_made", []),
            "expected_impact": suggestion.get("expected_impact"),
        }

    return {
        "status": "suggestion",
        "improved_prompt": suggestion.get("improved_prompt", ""),
        "changes_made": suggestion.get("changes_made", []),
        "expected_impact": suggestion.get("expected_impact"),
        "current_version": suggestion.get("current_version"),
    }


@router.post("/apply-prompt")
async def apply_prompt(
    request: ApplyPromptRequest,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Apply a new prompt version (manual or from suggestion)."""
    practice_id = _ensure_practice(current_user)

    pv = await apply_prompt_improvement(
        db, practice_id,
        new_prompt=request.prompt_text,
        change_reason=request.change_reason,
    )

    pushed = False
    if request.push_to_vapi:
        pushed = await push_prompt_to_vapi(practice_id, request.prompt_text, db)

    await db.commit()

    return {
        "status": "ok",
        "version": pv.version,
        "pushed_to_vapi": pushed,
    }


@router.get("/prompt-versions", response_model=list[PromptVersionResponse])
async def list_prompt_versions(
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """List prompt versions with their performance metrics."""
    practice_id = _ensure_practice(current_user)

    result = await db.execute(
        select(PromptVersion)
        .where(PromptVersion.practice_id == practice_id)
        .order_by(desc(PromptVersion.version))
        .limit(limit)
    )

    return [PromptVersionResponse.model_validate(pv) for pv in result.scalars().all()]
