"""
Feedback loop API routes -- AI-powered call transcript analysis and
prompt improvement suggestions.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_practice_admin, require_any_staff
from app.models.user import User
from app.scale.feedback_loop import FeedbackAnalyzer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/feedback-loop", tags=["Feedback Loop"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AnalyzeBatchRequest(BaseModel):
    days: int = Field(7, ge=1, le=30, description="Look back N days for unanalyzed calls")
    limit: int = Field(50, ge=1, le=200, description="Max calls to analyze in this batch")


class AnalysisResponse(BaseModel):
    call_id: str | None = None
    quality_score: int | None = None
    missed_intents: list[str] = []
    improvement_suggestions: list[str] = []
    frustration_detected: bool = False
    key_phrases: list[str] = []
    analyzed_at: str | None = None
    already_analyzed: bool = False
    error: str | None = None


class BatchResponse(BaseModel):
    total_analyzed: int = 0
    total_attempted: int | None = None
    avg_quality: float | None = None
    common_issues: list[dict] = []
    top_improvements: list[dict] = []
    errors: list[str] = []
    message: str | None = None


class InsightsResponse(BaseModel):
    avg_quality_score: float = 0
    quality_trend: str = "insufficient_data"
    top_missed_intents: list[dict] = []
    top_improvements: list[dict] = []
    frustration_rate: float = 0
    calls_analyzed: int = 0
    recommendation: str = ""
    period_days: int = 30


class PromptSuggestion(BaseModel):
    category: str
    current_behavior: str
    suggested_change: str
    expected_impact: str
    priority: str


class QualityTrendEntry(BaseModel):
    week_start: str
    week_end: str
    avg_quality: float
    calls_analyzed: int
    frustration_rate: float


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _ensure_practice(user: User) -> str:
    """Extract practice_id or raise 400 if the user has no practice."""
    if not user.practice_id:
        raise HTTPException(
            status_code=400,
            detail="No practice associated with this user",
        )
    return str(user.practice_id)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/analyze/{call_id}", response_model=AnalysisResponse)
async def analyze_single_call(
    call_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Analyze a single call transcript using AI.

    Requires practice_admin role. The call must belong to the user's practice.
    """
    practice_id = _ensure_practice(current_user)

    result = await FeedbackAnalyzer.analyze_call_transcript(
        db, practice_id, str(call_id)
    )

    if "error" in result and result.get("call_id") is None:
        raise HTTPException(status_code=400, detail=result["error"])

    return AnalysisResponse(**result)


@router.post("/analyze-batch", response_model=BatchResponse)
async def analyze_batch(
    body: AnalyzeBatchRequest = AnalyzeBatchRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Analyze a batch of recent unanalyzed call transcripts.

    Requires practice_admin role. Rate-limited to 1 call per second.
    """
    practice_id = _ensure_practice(current_user)

    result = await FeedbackAnalyzer.analyze_batch(
        db, practice_id, days=body.days, limit=body.limit
    )

    return BatchResponse(**result)


@router.get("/insights", response_model=InsightsResponse)
async def get_insights(
    days: int = Query(30, ge=1, le=90, description="Analysis period in days"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Get aggregated practice insights from call analyses.

    Returns quality trends, top missed intents, improvement areas,
    and an overall recommendation.
    """
    practice_id = _ensure_practice(current_user)

    result = await FeedbackAnalyzer.get_practice_insights(
        db, practice_id, days=days
    )

    return InsightsResponse(**result)


@router.get("/suggestions", response_model=list[PromptSuggestion])
async def get_suggestions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Generate AI prompt improvement suggestions based on recent analyses.

    Uses Claude to synthesize patterns from the last 14 days of call
    analyses into actionable prompt changes.
    """
    practice_id = _ensure_practice(current_user)

    suggestions = await FeedbackAnalyzer.generate_prompt_suggestions(
        db, practice_id
    )

    if not suggestions:
        return []

    return [PromptSuggestion(**s) for s in suggestions]


@router.get("/quality-trend", response_model=list[QualityTrendEntry])
async def get_quality_trend(
    weeks: int = Query(8, ge=1, le=52, description="Number of weeks to include"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_staff),
):
    """Get weekly call quality score trend for charting.

    Available to any staff member (secretary, practice_admin, super_admin).
    """
    practice_id = _ensure_practice(current_user)

    trend = await FeedbackAnalyzer.get_call_quality_trend(
        db, practice_id, weeks=weeks
    )

    return [QualityTrendEntry(**entry) for entry in trend]
