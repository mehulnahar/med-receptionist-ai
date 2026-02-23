"""
Self-Improving Feedback Loop Service.

This service analyzes each completed call and:
1. Scores call quality across multiple dimensions
2. Detects failure patterns
3. Generates improvement suggestions
4. Aggregates insights across calls
5. Can auto-apply prompt improvements when confident

The loop:
  Call ends → end-of-call-report → analyze_call_quality() → store feedback
  Every N calls → detect_patterns() → generate insights
  When pattern is strong → suggest_prompt_improvement() → admin approves or auto-applies
"""

import asyncio
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy import Integer, select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.utils.http_client import get_http_client
from app.models.call import Call
from app.models.feedback import CallFeedback, PromptVersion, FeedbackInsight

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM interface (uses OpenAI-compatible API)
# ---------------------------------------------------------------------------

_LLM_TIMEOUT = httpx.Timeout(45.0, connect=10.0, pool=5.0)
_LLM_MAX_RETRIES = 2


async def _call_llm(
    system_prompt: str,
    user_prompt: str,
    json_mode: bool = True,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> dict | str | None:
    """
    Call OpenAI LLM for analysis. Returns parsed JSON if json_mode else raw text.
    Falls back gracefully if no API key configured.
    Retries on transient errors (5xx, timeouts) up to _LLM_MAX_RETRIES times.

    Args:
        model: Override the default model (default: gpt-4o-mini).
        max_tokens: Override the default max_tokens (default: 1500).
        temperature: Override the default temperature (default: 0.2).
    """
    api_key = get_settings().OPENAI_API_KEY
    if not api_key:
        logger.debug("feedback_service: No OPENAI_API_KEY configured, skipping LLM analysis")
        return None

    import asyncio

    body = {
        "model": model or "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature if temperature is not None else 0.2,
        "max_tokens": max_tokens or 1500,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    last_error = None
    for attempt in range(_LLM_MAX_RETRIES + 1):
        try:
            client = get_http_client()
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=_LLM_TIMEOUT,
            )

            # Don't retry on client errors (4xx)
            if 400 <= resp.status_code < 500:
                logger.warning("feedback_service: LLM returned %d: %s", resp.status_code, resp.text[:200])
                return None

            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            if json_mode:
                return json.loads(content)
            return content

        except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
            last_error = e
            if attempt < _LLM_MAX_RETRIES:
                delay = 2 ** attempt
                logger.info("feedback_service: LLM call attempt %d failed (%s), retrying in %ds", attempt + 1, type(e).__name__, delay)
                await asyncio.sleep(delay)
                continue
        except Exception as e:
            logger.warning("feedback_service: LLM call failed: %s", e)
            return None

    logger.warning("feedback_service: LLM call failed after %d attempts: %s", _LLM_MAX_RETRIES + 1, last_error)
    return None


# ---------------------------------------------------------------------------
# 1. Per-call quality analysis (runs after every call)
# ---------------------------------------------------------------------------

CALL_ANALYSIS_SYSTEM_PROMPT = """You are a quality analyst for an AI medical receptionist named Jenny.
Analyze this call transcript and data to score quality and identify improvements.

Return JSON with these fields:
{
  "overall_score": 0.0-1.0,
  "resolution_score": 0.0-1.0 (did caller's need get resolved?),
  "efficiency_score": 0.0-1.0 (how quickly and smoothly?),
  "empathy_score": 0.0-1.0 (was Jenny warm, patient, caring?),
  "accuracy_score": 0.0-1.0 (were tool calls and info correct?),
  "was_successful": true/false,
  "failure_point": null or string (where did it go wrong? e.g. "dob_collection", "booking_confirmation", "language_switch", "greeting"),
  "failure_reason": null or string (why? be specific),
  "improvement_suggestion": null or string (concrete prompt change to fix this),
  "call_complexity": "simple"/"moderate"/"complex",
  "caller_dropped": true/false (did caller hang up frustrated?),
  "key_observations": ["observation 1", "observation 2"]
}

Scoring guide:
- 0.9-1.0: Excellent — resolved perfectly, warm, efficient
- 0.7-0.89: Good — resolved with minor issues
- 0.5-0.69: Needs improvement — resolved but awkwardly
- 0.3-0.49: Poor — partially resolved or caller frustrated
- 0.0-0.29: Failed — caller need unresolved or call dropped

Be honest and specific. Focus on actionable improvements."""


async def analyze_call_quality(
    db: AsyncSession,
    call_id: UUID,
) -> Optional[CallFeedback]:
    """
    Analyze a single call's quality and create a CallFeedback record.
    Called after the end-of-call-report is saved.
    """
    # Fetch the call
    result = await db.execute(select(Call).where(Call.id == call_id))
    call = result.scalar_one_or_none()
    if not call:
        return None

    # Skip very short calls (likely wrong numbers or instant hangups)
    if call.duration_seconds is not None and call.duration_seconds < 5:
        return None

    # Check if already analyzed
    existing = await db.execute(
        select(CallFeedback).where(CallFeedback.call_id == call_id)
    )
    if existing.scalar_one_or_none():
        return None

    # Build the analysis prompt
    transcript = call.transcription or "(no transcript available)"
    structured = call.structured_data or {}

    user_prompt = f"""Call ID: {call.id}
Duration: {call.duration_seconds or 'unknown'} seconds
End reason: {call.outcome or 'unknown'}
Language: {call.language or 'en'}
Caller: {call.caller_name or 'unknown'}
Vapi success evaluation: {call.success_evaluation or 'unknown'}

Structured data extracted by Vapi:
{json.dumps(structured, indent=2) if structured else '(none)'}

AI Summary: {call.ai_summary or '(none)'}

Transcript:
{transcript[:8000]}"""

    # Call LLM for analysis
    analysis = await _call_llm(CALL_ANALYSIS_SYSTEM_PROMPT, user_prompt)

    if not analysis or not isinstance(analysis, dict):
        # Fallback: basic scoring from Vapi data
        analysis = _basic_scoring(call)

    # Get current prompt version
    version_result = await db.execute(
        select(PromptVersion.version)
        .where(
            PromptVersion.practice_id == call.practice_id,
            PromptVersion.is_active == True,
        )
        .limit(1)
    )
    current_version = version_result.scalar_one_or_none()

    # Create feedback record
    feedback = CallFeedback(
        call_id=call.id,
        practice_id=call.practice_id,
        overall_score=analysis.get("overall_score"),
        resolution_score=analysis.get("resolution_score"),
        efficiency_score=analysis.get("efficiency_score"),
        empathy_score=analysis.get("empathy_score"),
        accuracy_score=analysis.get("accuracy_score"),
        failure_point=analysis.get("failure_point"),
        failure_reason=analysis.get("failure_reason"),
        improvement_suggestion=analysis.get("improvement_suggestion"),
        call_complexity=analysis.get("call_complexity"),
        language_detected=call.language or structured.get("language", "en"),
        was_successful=analysis.get("was_successful"),
        caller_dropped=analysis.get("caller_dropped", False),
        raw_analysis=analysis,
        prompt_version=current_version,
    )
    db.add(feedback)
    await db.flush()
    await db.refresh(feedback)

    # Update prompt version metrics
    if current_version:
        await _update_prompt_metrics(db, call.practice_id, current_version)

    logger.info(
        "feedback_service: analyzed call %s — score=%.2f success=%s failure=%s",
        call.id,
        analysis.get("overall_score", 0),
        analysis.get("was_successful"),
        analysis.get("failure_point"),
    )

    return feedback


def _basic_scoring(call: Call) -> dict:
    """Fallback scoring when LLM is unavailable. Uses Vapi data."""
    score = 0.5  # Start neutral

    # Adjust based on end reason
    good_endings = {"assistant-ended-call", "customer-ended-call"}
    bad_endings = {
        "customer-did-not-answer", "customer-busy",
        "assistant-error", "phone-call-provider-closed-websocket",
    }

    if call.outcome in good_endings:
        score += 0.2
    elif call.outcome in bad_endings:
        score -= 0.3

    # Adjust based on duration (too short = likely failed)
    if call.duration_seconds:
        if call.duration_seconds > 30:
            score += 0.1
        if call.duration_seconds < 15:
            score -= 0.2

    # Adjust based on success evaluation
    if call.success_evaluation == "true":
        score += 0.2
    elif call.success_evaluation == "false":
        score -= 0.2

    # Adjust based on structured data
    structured = call.structured_data or {}
    if structured.get("appointment_booked"):
        score += 0.1
    if structured.get("caller_sentiment") == "frustrated":
        score -= 0.2
    elif structured.get("caller_sentiment") == "positive":
        score += 0.1

    score = max(0.0, min(1.0, score))

    was_successful = score >= 0.5
    failure_point = None
    if not was_successful:
        if call.outcome in bad_endings:
            failure_point = "call_connection"
        elif call.duration_seconds and call.duration_seconds < 15:
            failure_point = "early_dropout"
        else:
            failure_point = "unknown"

    return {
        "overall_score": round(score, 2),
        "resolution_score": round(score, 2),
        "efficiency_score": 0.5,
        "empathy_score": 0.5,
        "accuracy_score": 0.5,
        "was_successful": was_successful,
        "failure_point": failure_point,
        "failure_reason": None,
        "improvement_suggestion": None,
        "call_complexity": "simple",
        "caller_dropped": call.outcome in bad_endings,
        "key_observations": [],
    }


# ---------------------------------------------------------------------------
# 2. Pattern detection (runs periodically or after N calls)
# ---------------------------------------------------------------------------

PATTERN_DETECTION_SYSTEM_PROMPT = """You are a quality improvement analyst for an AI medical receptionist.
You're reviewing multiple call feedback records to detect patterns.

Identify recurring issues and opportunities for improvement.
Return JSON:
{
  "insights": [
    {
      "type": "failure_pattern" | "improvement_opportunity" | "language_issue" | "flow_optimization",
      "category": "booking" | "greeting" | "scheduling" | "transfer" | "spanish" | "data_collection" | "general",
      "severity": "low" | "medium" | "high" | "critical",
      "title": "Short descriptive title",
      "description": "Detailed description of the pattern",
      "suggested_fix": "Specific prompt change to address this",
      "affected_call_count": number
    }
  ]
}

Focus on patterns that appear in 3+ calls. Be specific about prompt changes."""


async def detect_patterns(
    db: AsyncSession,
    practice_id: UUID,
    lookback_hours: int = 24,
) -> list[FeedbackInsight]:
    """
    Analyze recent call feedback to detect patterns and generate insights.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    # Fetch recent feedback
    result = await db.execute(
        select(CallFeedback)
        .where(
            CallFeedback.practice_id == practice_id,
            CallFeedback.created_at >= cutoff,
        )
        .order_by(desc(CallFeedback.created_at))
        .limit(100)
    )
    feedbacks = result.scalars().all()

    if len(feedbacks) < 3:
        logger.info("feedback_service: not enough calls (%d) for pattern detection", len(feedbacks))
        return []

    # Build analysis prompt
    feedback_summaries = []
    for fb in feedbacks:
        feedback_summaries.append({
            "call_id": str(fb.call_id),
            "score": fb.overall_score,
            "was_successful": fb.was_successful,
            "failure_point": fb.failure_point,
            "failure_reason": fb.failure_reason,
            "improvement_suggestion": fb.improvement_suggestion,
            "language": fb.language_detected,
            "complexity": fb.call_complexity,
            "caller_dropped": fb.caller_dropped,
        })

    user_prompt = f"""Analyzing {len(feedbacks)} recent calls for practice.

Call feedback data:
{json.dumps(feedback_summaries, indent=2)}

Aggregate stats:
- Total calls: {len(feedbacks)}
- Successful: {sum(1 for f in feedbacks if f.was_successful)}
- Failed: {sum(1 for f in feedbacks if not f.was_successful)}
- Average score: {sum(f.overall_score or 0 for f in feedbacks) / len(feedbacks):.2f}
- Caller dropouts: {sum(1 for f in feedbacks if f.caller_dropped)}
- Spanish calls: {sum(1 for f in feedbacks if f.language_detected == 'es')}

Common failure points: {json.dumps(dict(_count_values([f.failure_point for f in feedbacks if f.failure_point])))}"""

    analysis = await _call_llm(PATTERN_DETECTION_SYSTEM_PROMPT, user_prompt)

    if not analysis or "insights" not in analysis:
        return []

    # Store insights
    new_insights = []
    for insight_data in analysis["insights"]:
        # Check if a similar insight already exists (avoid duplicates)
        existing = await db.execute(
            select(FeedbackInsight).where(
                FeedbackInsight.practice_id == practice_id,
                FeedbackInsight.title == insight_data["title"],
                FeedbackInsight.status == "open",
            )
        )
        if existing.scalar_one_or_none():
            continue

        insight = FeedbackInsight(
            practice_id=practice_id,
            insight_type=insight_data.get("type", "improvement_opportunity"),
            category=insight_data.get("category", "general"),
            severity=insight_data.get("severity", "medium"),
            title=insight_data["title"],
            description=insight_data["description"],
            suggested_fix=insight_data.get("suggested_fix"),
            affected_calls=insight_data.get("affected_call_count", 0),
        )
        db.add(insight)
        new_insights.append(insight)

    if new_insights:
        await db.flush()
        logger.info(
            "feedback_service: detected %d new insights for practice %s",
            len(new_insights), practice_id,
        )

    return new_insights


def _count_values(items: list) -> list[tuple]:
    """Count occurrences of each value in a list."""
    counts = {}
    for item in items:
        if item:
            counts[item] = counts.get(item, 0) + 1
    return sorted(counts.items(), key=lambda x: -x[1])


# ---------------------------------------------------------------------------
# 3. Prompt improvement (manual or auto-apply)
# ---------------------------------------------------------------------------

PROMPT_IMPROVEMENT_SYSTEM_PROMPT = """You are a prompt engineer optimizing an AI medical receptionist.
Given the current system prompt and the insights from call analysis, generate an improved prompt.

Rules:
1. Keep the same overall structure and personality
2. Only modify sections relevant to the insights
3. Be specific about what changed and why
4. The prompt should be in the same language/format as the original
5. Don't remove any existing tool call instructions
6. Keep it natural and conversational

Return JSON:
{
  "improved_prompt": "The full improved system prompt text",
  "changes_made": ["Change 1 description", "Change 2 description"],
  "expected_impact": "What improvement to expect"
}"""


async def generate_prompt_improvement(
    db: AsyncSession,
    practice_id: UUID,
    insight_ids: list[UUID] | None = None,
) -> dict | None:
    """
    Generate an improved system prompt based on feedback insights.
    Does NOT auto-apply — returns the suggestion for admin review.
    """
    # Get current active prompt
    current = await db.execute(
        select(PromptVersion)
        .where(
            PromptVersion.practice_id == practice_id,
            PromptVersion.is_active == True,
        )
        .limit(1)
    )
    current_version = current.scalar_one_or_none()

    if not current_version:
        # Get it from Vapi instead
        current_prompt = await _fetch_current_vapi_prompt(db, practice_id)
        if not current_prompt:
            return None
    else:
        current_prompt = current_version.prompt_text

    # Get open insights
    if insight_ids:
        insights_result = await db.execute(
            select(FeedbackInsight).where(
                FeedbackInsight.id.in_(insight_ids),
                FeedbackInsight.practice_id == practice_id,
            )
        )
    else:
        insights_result = await db.execute(
            select(FeedbackInsight).where(
                FeedbackInsight.practice_id == practice_id,
                FeedbackInsight.status == "open",
            )
            .order_by(desc(FeedbackInsight.created_at))
            .limit(10)
        )

    insights = insights_result.scalars().all()

    if not insights:
        return None

    insights_text = "\n".join([
        f"- [{i.severity}] {i.title}: {i.description}\n  Suggested fix: {i.suggested_fix}"
        for i in insights
    ])

    user_prompt = f"""Current system prompt:
---
{current_prompt[:6000]}
---

Insights from call analysis:
{insights_text}

Generate an improved version of the system prompt that addresses these insights."""

    result = await _call_llm(PROMPT_IMPROVEMENT_SYSTEM_PROMPT, user_prompt)

    if result:
        result["current_version"] = current_version.version if current_version else 0
        result["insight_ids"] = [str(i.id) for i in insights]

    return result


async def apply_prompt_improvement(
    db: AsyncSession,
    practice_id: UUID,
    new_prompt: str,
    change_reason: str,
    change_diff: str | None = None,
) -> PromptVersion:
    """
    Save a new prompt version and optionally push it to Vapi.
    """
    # Get current max version
    result = await db.execute(
        select(func.max(PromptVersion.version))
        .where(PromptVersion.practice_id == practice_id)
    )
    max_version = result.scalar_one_or_none() or 0

    # Deactivate current active version
    current = await db.execute(
        select(PromptVersion)
        .where(
            PromptVersion.practice_id == practice_id,
            PromptVersion.is_active == True,
        )
    )
    for pv in current.scalars().all():
        pv.is_active = False
        pv.deactivated_at = datetime.now(timezone.utc)

    # Create new version
    new_version = PromptVersion(
        practice_id=practice_id,
        version=max_version + 1,
        prompt_text=new_prompt,
        change_reason=change_reason,
        change_diff=change_diff,
        is_active=True,
        activated_at=datetime.now(timezone.utc),
    )
    db.add(new_version)
    await db.flush()
    await db.refresh(new_version)

    logger.info(
        "feedback_service: created prompt version %d for practice %s: %s",
        new_version.version, practice_id, change_reason,
    )

    return new_version


async def push_prompt_to_vapi(
    practice_id: UUID,
    prompt_text: str,
    db: AsyncSession,
) -> bool:
    """Push an updated system prompt to the Vapi assistant."""
    from app.models.practice_config import PracticeConfig

    result = await db.execute(
        select(PracticeConfig).where(PracticeConfig.practice_id == practice_id)
    )
    config = result.scalar_one_or_none()

    if not config or not config.vapi_assistant_id:
        logger.warning("feedback_service: no Vapi assistant ID for practice %s", practice_id)
        return False

    # Use per-practice Vapi API key, falling back to global key
    vapi_key = getattr(config, "vapi_api_key", None) or get_settings().VAPI_API_KEY
    if not vapi_key:
        logger.warning("feedback_service: no Vapi API key for practice %s", practice_id)
        return False

    try:
        client = get_http_client()
        resp = await client.patch(
            f"https://api.vapi.ai/assistant/{config.vapi_assistant_id}",
            headers={
                "Authorization": f"Bearer {vapi_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": {
                    "messages": [
                        {"role": "system", "content": prompt_text}
                    ]
                }
            },
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("feedback_service: pushed prompt to Vapi assistant %s", config.vapi_assistant_id)
        return True

    except Exception as e:
        logger.error("feedback_service: failed to push prompt to Vapi: %s", e)
        return False


async def _fetch_current_vapi_prompt(db: AsyncSession, practice_id: UUID) -> str | None:
    """Fetch the current system prompt from Vapi assistant.

    Accepts the caller's db session to avoid creating a standalone session
    that could leak connections if the Vapi API call hangs.
    """
    try:
        from app.models.practice_config import PracticeConfig

        result = await db.execute(
            select(PracticeConfig).where(PracticeConfig.practice_id == practice_id)
        )
        config = result.scalar_one_or_none()

        if not config or not config.vapi_assistant_id:
            return None

        # Use per-practice Vapi API key, falling back to global key
        vapi_key = getattr(config, "vapi_api_key", None) or get_settings().VAPI_API_KEY
        if not vapi_key:
            return None

        client = get_http_client()
        resp = await client.get(
            f"https://api.vapi.ai/assistant/{config.vapi_assistant_id}",
            headers={"Authorization": f"Bearer {vapi_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        messages = data.get("model", {}).get("messages", [])
        for msg in messages:
            if msg.get("role") == "system":
                return msg["content"]
    except Exception as e:
        logger.warning("feedback_service: failed to fetch Vapi prompt: %s", e)

    return None


# ---------------------------------------------------------------------------
# 4. Prompt metrics update
# ---------------------------------------------------------------------------

async def _update_prompt_metrics(
    db: AsyncSession,
    practice_id: UUID,
    version: int,
):
    """Update performance metrics for a prompt version."""
    result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.practice_id == practice_id,
            PromptVersion.version == version,
        )
    )
    pv = result.scalar_one_or_none()
    if not pv:
        return

    # Count calls and scores for this version
    feedback_result = await db.execute(
        select(
            func.count(CallFeedback.id),
            func.sum(func.cast(CallFeedback.was_successful, Integer)),
            func.avg(CallFeedback.overall_score),
        ).where(
            CallFeedback.practice_id == practice_id,
            CallFeedback.prompt_version == version,
        )
    )
    row = feedback_result.one()

    pv.total_calls = row[0] or 0
    pv.successful_calls = row[1] or 0
    pv.avg_score = float(row[2]) if row[2] else None

    # Calculate booking rate — scoped to calls with feedback for THIS prompt version
    call_result = await db.execute(
        select(func.count(Call.id))
        .join(CallFeedback, CallFeedback.call_id == Call.id)
        .where(
            Call.practice_id == practice_id,
            Call.appointment_id.isnot(None),
            CallFeedback.prompt_version == version,
        )
    )
    booked = call_result.scalar_one() or 0
    if pv.total_calls > 0:
        pv.booking_rate = booked / pv.total_calls

    await db.flush()


# ---------------------------------------------------------------------------
# 5. Main entry point (called from webhook handler)
# ---------------------------------------------------------------------------

async def process_call_feedback(
    db: AsyncSession,
    call_id: UUID,
    practice_id: UUID,
):
    """
    Main entry point for the feedback loop. Called after end-of-call-report.
    Runs analysis, and triggers pattern detection every 10 calls.
    """
    # Step 1: Analyze this call
    feedback = await analyze_call_quality(db, call_id)

    if not feedback:
        return

    # Step 2: Check if we should run pattern detection
    # (every 10 calls or when we see a bad call)
    count_result = await db.execute(
        select(func.count(CallFeedback.id)).where(
            CallFeedback.practice_id == practice_id,
        )
    )
    total_feedback = count_result.scalar_one()

    should_detect_patterns = (
        total_feedback % 10 == 0  # Every 10 calls
        or (feedback.overall_score is not None and feedback.overall_score < 0.3)  # Bad call
    )

    if should_detect_patterns:
        await detect_patterns(db, practice_id)

    # NOTE: commit/rollback is the caller's responsibility (_run_feedback_analysis)
    await db.flush()
