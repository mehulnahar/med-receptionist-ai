"""
AI self-improvement feedback loop service.

Analyzes call transcripts using Claude to detect quality issues,
missed intents, frustration patterns, and generates actionable
prompt improvement suggestions. Runs periodically or on-demand
to drive continuous improvement of the AI receptionist.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

logger = logging.getLogger(__name__)


class FeedbackAnalyzer:
    """Analyzes call transcripts with Claude to improve AI performance."""

    # -------------------------------------------------------------------
    # 1. Single call analysis
    # -------------------------------------------------------------------

    @staticmethod
    async def analyze_call_transcript(
        db: AsyncSession,
        practice_id: str,
        call_id: str,
    ) -> dict:
        """Analyze a single call transcript for quality, missed intents, and frustration.

        Saves results to the ``call_analyses`` table and returns the analysis dict.
        """
        settings = get_settings()

        if not settings.ANTHROPIC_API_KEY:
            logger.warning("ANTHROPIC_API_KEY not set — skipping transcript analysis")
            return {"error": "ANTHROPIC_API_KEY not configured"}

        # Fetch the call record
        result = await db.execute(
            text("""
                SELECT id, practice_id, transcript, outcome, caller_intent,
                       caller_sentiment, status, duration_seconds, started_at
                FROM calls
                WHERE id = :call_id AND practice_id = :practice_id
            """),
            {"call_id": call_id, "practice_id": practice_id},
        )
        call = result.fetchone()

        if not call:
            return {"error": "Call not found"}

        if not call.transcript:
            return {"error": "Call has no transcript to analyze"}

        # Check if already analyzed
        existing = await db.execute(
            text("SELECT id FROM call_analyses WHERE call_id = :call_id"),
            {"call_id": call_id},
        )
        if existing.fetchone():
            # Return existing analysis
            row = await db.execute(
                text("""
                    SELECT quality_score, missed_intents, improvement_suggestions,
                           frustration_detected, key_phrases, analyzed_at
                    FROM call_analyses WHERE call_id = :call_id
                """),
                {"call_id": call_id},
            )
            existing_analysis = row.fetchone()
            return {
                "call_id": call_id,
                "quality_score": existing_analysis.quality_score,
                "missed_intents": existing_analysis.missed_intents or [],
                "improvement_suggestions": existing_analysis.improvement_suggestions or [],
                "frustration_detected": existing_analysis.frustration_detected,
                "key_phrases": existing_analysis.key_phrases or [],
                "analyzed_at": existing_analysis.analyzed_at.isoformat() if existing_analysis.analyzed_at else None,
                "already_analyzed": True,
            }

        # Build the analysis prompt
        prompt = _build_analysis_prompt(
            transcript=call.transcript,
            outcome=call.outcome,
            caller_intent=call.caller_intent,
            caller_sentiment=call.caller_sentiment,
            duration_seconds=call.duration_seconds,
        )

        # Call Claude API
        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            message = await client.messages.create(
                model=settings.CLAUDE_SONNET_MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = message.content[0].text
            analysis = _parse_analysis_response(response_text)

        except Exception as e:
            logger.error("Claude API call failed for call %s: %s", call_id, e)
            return {"error": f"Analysis failed: {str(e)}"}

        # Save to call_analyses table
        await db.execute(
            text("""
                INSERT INTO call_analyses (
                    id, practice_id, call_id, quality_score,
                    missed_intents, improvement_suggestions,
                    frustration_detected, key_phrases, analyzed_at
                ) VALUES (
                    gen_random_uuid(), :practice_id, :call_id, :quality_score,
                    :missed_intents, :improvement_suggestions,
                    :frustration_detected, :key_phrases, NOW()
                )
            """),
            {
                "practice_id": practice_id,
                "call_id": call_id,
                "quality_score": analysis["quality_score"],
                "missed_intents": analysis["missed_intents"],
                "improvement_suggestions": analysis["improvement_suggestions"],
                "frustration_detected": analysis["frustration_detected"],
                "key_phrases": analysis["key_phrases"],
            },
        )
        await db.commit()

        logger.info(
            "Analyzed call %s: quality=%d, frustration=%s",
            call_id, analysis["quality_score"], analysis["frustration_detected"],
        )

        return {
            "call_id": call_id,
            "quality_score": analysis["quality_score"],
            "missed_intents": analysis["missed_intents"],
            "improvement_suggestions": analysis["improvement_suggestions"],
            "frustration_detected": analysis["frustration_detected"],
            "key_phrases": analysis["key_phrases"],
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "already_analyzed": False,
        }

    # -------------------------------------------------------------------
    # 2. Batch analysis
    # -------------------------------------------------------------------

    @staticmethod
    async def analyze_batch(
        db: AsyncSession,
        practice_id: str,
        days: int = 7,
        limit: int = 50,
    ) -> dict:
        """Analyze recent calls that haven't been analyzed yet.

        Rate-limits to 1 call per second to avoid API throttling.
        Returns a summary of the batch run.
        """
        # Find calls with transcripts that haven't been analyzed
        result = await db.execute(
            text("""
                SELECT c.id
                FROM calls c
                LEFT JOIN call_analyses ca ON ca.call_id = c.id
                WHERE c.practice_id = :practice_id
                  AND c.transcript IS NOT NULL
                  AND c.transcript != ''
                  AND c.started_at >= NOW() - (:days || ' days')::interval
                  AND ca.id IS NULL
                ORDER BY c.started_at DESC
                LIMIT :limit
            """),
            {"practice_id": practice_id, "days": days, "limit": limit},
        )
        call_ids = [str(row.id) for row in result.fetchall()]

        if not call_ids:
            return {
                "total_analyzed": 0,
                "avg_quality": None,
                "common_issues": [],
                "top_improvements": [],
                "message": "No unanalyzed calls found",
            }

        analyzed = 0
        quality_scores: list[int] = []
        all_issues: list[str] = []
        all_improvements: list[str] = []
        errors: list[str] = []

        for call_id in call_ids:
            try:
                analysis = await FeedbackAnalyzer.analyze_call_transcript(
                    db, practice_id, call_id
                )

                if "error" in analysis:
                    errors.append(f"{call_id}: {analysis['error']}")
                    continue

                analyzed += 1
                quality_scores.append(analysis["quality_score"])
                all_issues.extend(analysis.get("missed_intents", []))
                all_improvements.extend(analysis.get("improvement_suggestions", []))

            except Exception as e:
                errors.append(f"{call_id}: {str(e)}")
                logger.warning("Batch analysis failed for call %s: %s", call_id, e)

            # Rate limit: 1 call per second
            await asyncio.sleep(1.0)

        # Aggregate results
        avg_quality = (
            round(sum(quality_scores) / len(quality_scores), 1)
            if quality_scores else None
        )

        # Count frequency of issues and improvements
        common_issues = _get_top_items(all_issues, top_n=5)
        top_improvements = _get_top_items(all_improvements, top_n=5)

        return {
            "total_analyzed": analyzed,
            "total_attempted": len(call_ids),
            "avg_quality": avg_quality,
            "common_issues": common_issues,
            "top_improvements": top_improvements,
            "errors": errors[:10] if errors else [],
        }

    # -------------------------------------------------------------------
    # 3. Practice insights (aggregated)
    # -------------------------------------------------------------------

    @staticmethod
    async def get_practice_insights(
        db: AsyncSession,
        practice_id: str,
        days: int = 30,
    ) -> dict:
        """Aggregate analysis data for a practice over a time period.

        Returns quality trends, top missed intents, improvement areas,
        and an overall recommendation.
        """
        # Aggregate stats
        result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS calls_analyzed,
                    COALESCE(AVG(quality_score), 0) AS avg_quality,
                    COUNT(*) FILTER (WHERE frustration_detected = TRUE) AS frustrated_calls
                FROM call_analyses
                WHERE practice_id = :practice_id
                  AND analyzed_at >= NOW() - (:days || ' days')::interval
            """),
            {"practice_id": practice_id, "days": days},
        )
        stats = result.fetchone()

        calls_analyzed = stats.calls_analyzed or 0
        avg_quality = round(float(stats.avg_quality), 1) if stats.avg_quality else 0
        frustration_rate = (
            round(stats.frustrated_calls / calls_analyzed * 100, 1)
            if calls_analyzed > 0 else 0
        )

        # Quality trend: compare first half vs second half of the period
        half_days = max(days // 2, 1)
        trend_result = await db.execute(
            text("""
                SELECT
                    AVG(CASE WHEN analyzed_at < NOW() - (:half_days || ' days')::interval
                        THEN quality_score END) AS older_avg,
                    AVG(CASE WHEN analyzed_at >= NOW() - (:half_days || ' days')::interval
                        THEN quality_score END) AS newer_avg
                FROM call_analyses
                WHERE practice_id = :practice_id
                  AND analyzed_at >= NOW() - (:days || ' days')::interval
            """),
            {"practice_id": practice_id, "days": days, "half_days": half_days},
        )
        trend_row = trend_result.fetchone()
        older_avg = float(trend_row.older_avg) if trend_row.older_avg else None
        newer_avg = float(trend_row.newer_avg) if trend_row.newer_avg else None

        if older_avg is not None and newer_avg is not None:
            diff = newer_avg - older_avg
            if diff > 0.5:
                quality_trend = "improving"
            elif diff < -0.5:
                quality_trend = "declining"
            else:
                quality_trend = "stable"
        else:
            quality_trend = "insufficient_data"

        # Top missed intents (unnest the text[] column)
        missed_result = await db.execute(
            text("""
                SELECT unnest(missed_intents) AS intent, COUNT(*) AS cnt
                FROM call_analyses
                WHERE practice_id = :practice_id
                  AND analyzed_at >= NOW() - (:days || ' days')::interval
                  AND missed_intents IS NOT NULL
                  AND array_length(missed_intents, 1) > 0
                GROUP BY intent
                ORDER BY cnt DESC
                LIMIT 5
            """),
            {"practice_id": practice_id, "days": days},
        )
        top_missed_intents = [
            {"intent": row.intent, "count": row.cnt}
            for row in missed_result.fetchall()
        ]

        # Top improvement suggestions
        improvements_result = await db.execute(
            text("""
                SELECT unnest(improvement_suggestions) AS suggestion, COUNT(*) AS cnt
                FROM call_analyses
                WHERE practice_id = :practice_id
                  AND analyzed_at >= NOW() - (:days || ' days')::interval
                  AND improvement_suggestions IS NOT NULL
                  AND array_length(improvement_suggestions, 1) > 0
                GROUP BY suggestion
                ORDER BY cnt DESC
                LIMIT 5
            """),
            {"practice_id": practice_id, "days": days},
        )
        top_improvements = [
            {"suggestion": row.suggestion, "count": row.cnt}
            for row in improvements_result.fetchall()
        ]

        # Generate recommendation
        recommendation = _generate_recommendation(
            avg_quality, quality_trend, frustration_rate, calls_analyzed,
        )

        return {
            "avg_quality_score": avg_quality,
            "quality_trend": quality_trend,
            "top_missed_intents": top_missed_intents,
            "top_improvements": top_improvements,
            "frustration_rate": frustration_rate,
            "calls_analyzed": calls_analyzed,
            "recommendation": recommendation,
            "period_days": days,
        }

    # -------------------------------------------------------------------
    # 4. Prompt improvement suggestions
    # -------------------------------------------------------------------

    @staticmethod
    async def generate_prompt_suggestions(
        db: AsyncSession,
        practice_id: str,
    ) -> list[dict]:
        """Synthesize recent analyses into actionable prompt improvement suggestions.

        Uses Claude to review aggregated issues and generate specific changes.
        """
        settings = get_settings()

        if not settings.ANTHROPIC_API_KEY:
            logger.warning("ANTHROPIC_API_KEY not set — cannot generate suggestions")
            return []

        # Gather recent analysis data (last 14 days)
        analyses_result = await db.execute(
            text("""
                SELECT missed_intents, improvement_suggestions,
                       frustration_detected, quality_score
                FROM call_analyses
                WHERE practice_id = :practice_id
                  AND analyzed_at >= NOW() - interval '14 days'
                ORDER BY analyzed_at DESC
                LIMIT 100
            """),
            {"practice_id": practice_id},
        )
        analyses = analyses_result.fetchall()

        if not analyses:
            return []

        # Aggregate the data for the synthesis prompt
        all_missed: list[str] = []
        all_suggestions: list[str] = []
        frustration_count = 0
        scores: list[int] = []

        for row in analyses:
            if row.missed_intents:
                all_missed.extend(row.missed_intents)
            if row.improvement_suggestions:
                all_suggestions.extend(row.improvement_suggestions)
            if row.frustration_detected:
                frustration_count += 1
            scores.append(row.quality_score)

        avg_score = round(sum(scores) / len(scores), 1) if scores else 0
        frustration_pct = (
            round(frustration_count / len(analyses) * 100, 1)
            if analyses else 0
        )

        # Count frequencies
        missed_counts = _get_top_items(all_missed, top_n=10)
        suggestion_counts = _get_top_items(all_suggestions, top_n=10)

        prompt = _build_suggestions_prompt(
            avg_score=avg_score,
            frustration_pct=frustration_pct,
            total_analyzed=len(analyses),
            missed_counts=missed_counts,
            suggestion_counts=suggestion_counts,
        )

        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            message = await client.messages.create(
                model=settings.CLAUDE_SONNET_MODEL,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = message.content[0].text
            suggestions = _parse_suggestions_response(response_text)
            return suggestions

        except Exception as e:
            logger.error("Claude API call failed for prompt suggestions: %s", e)
            return []

    # -------------------------------------------------------------------
    # 5. Quality trend (weekly)
    # -------------------------------------------------------------------

    @staticmethod
    async def get_call_quality_trend(
        db: AsyncSession,
        practice_id: str,
        weeks: int = 8,
    ) -> list[dict]:
        """Get weekly quality score averages for charting.

        Returns one entry per week with avg quality, call count,
        and frustration rate.
        """
        result = await db.execute(
            text("""
                SELECT
                    date_trunc('week', analyzed_at)::date AS week_start,
                    (date_trunc('week', analyzed_at) + interval '6 days')::date AS week_end,
                    ROUND(AVG(quality_score)::numeric, 1) AS avg_quality,
                    COUNT(*) AS calls_analyzed,
                    ROUND(
                        (COUNT(*) FILTER (WHERE frustration_detected = TRUE)::numeric
                         / NULLIF(COUNT(*), 0) * 100), 1
                    ) AS frustration_rate
                FROM call_analyses
                WHERE practice_id = :practice_id
                  AND analyzed_at >= NOW() - (:weeks || ' weeks')::interval
                GROUP BY week_start, week_end
                ORDER BY week_start ASC
            """),
            {"practice_id": practice_id, "weeks": weeks},
        )

        return [
            {
                "week_start": str(row.week_start),
                "week_end": str(row.week_end),
                "avg_quality": float(row.avg_quality) if row.avg_quality else 0,
                "calls_analyzed": row.calls_analyzed,
                "frustration_rate": float(row.frustration_rate) if row.frustration_rate else 0,
            }
            for row in result.fetchall()
        ]


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_analysis_prompt(
    transcript: str,
    outcome: Optional[str],
    caller_intent: Optional[str],
    caller_sentiment: Optional[str],
    duration_seconds: Optional[int],
) -> str:
    """Build the Claude prompt for analyzing a single call transcript."""
    # Truncate very long transcripts to stay within token limits
    max_chars = 8000
    if len(transcript) > max_chars:
        transcript = transcript[:max_chars] + "\n... [truncated]"

    return f"""You are a medical receptionist call quality analyst. Analyze this call transcript and provide a structured assessment.

CALL METADATA:
- Outcome: {outcome or 'unknown'}
- Detected caller intent: {caller_intent or 'unknown'}
- Detected caller sentiment: {caller_sentiment or 'unknown'}
- Duration: {duration_seconds or 'unknown'} seconds

TRANSCRIPT:
{transcript}

Analyze the call and respond ONLY with valid JSON (no markdown, no code fences):
{{
    "quality_score": <integer 1-10, where 10 is perfect handling>,
    "handled_well": <true/false>,
    "missed_intents": [<list of caller intents the AI missed or misunderstood, empty if none>],
    "improvement_suggestions": [<list of specific, actionable improvement suggestions>],
    "frustration_detected": <true/false - was there caller frustration or confusion?>,
    "frustration_reason": "<brief explanation if frustration detected, null otherwise>",
    "key_phrases": [<important medical terms, names, or requests mentioned>]
}}

Scoring guide:
- 9-10: Excellent handling, all intents addressed, caller satisfied
- 7-8: Good handling, minor missed opportunities
- 5-6: Adequate but notable issues (missed follow-up, slow response)
- 3-4: Poor handling, multiple missed intents or frustrated caller
- 1-2: Call failure, wrong information, or caller abandoned

Be specific in suggestions. Instead of "improve response time", say "add proactive confirmation of appointment date after booking"."""


def _build_suggestions_prompt(
    avg_score: float,
    frustration_pct: float,
    total_analyzed: int,
    missed_counts: list[dict],
    suggestion_counts: list[dict],
) -> str:
    """Build the Claude prompt for generating prompt improvement suggestions."""
    missed_str = "\n".join(
        f"  - {item['item']} ({item['count']} occurrences)"
        for item in missed_counts
    ) or "  None detected"

    suggestion_str = "\n".join(
        f"  - {item['item']} ({item['count']} occurrences)"
        for item in suggestion_counts
    ) or "  None detected"

    return f"""You are an AI prompt engineer specializing in medical receptionist systems. Based on analysis of {total_analyzed} recent calls, generate specific prompt improvement suggestions.

PERFORMANCE SUMMARY:
- Average quality score: {avg_score}/10
- Frustration rate: {frustration_pct}%
- Total calls analyzed: {total_analyzed}

TOP MISSED INTENTS:
{missed_str}

TOP RECURRING IMPROVEMENT SUGGESTIONS:
{suggestion_str}

Generate 3-5 specific, actionable prompt changes. Respond ONLY with valid JSON (no markdown, no code fences):
[
    {{
        "category": "<category: greeting, intent_detection, scheduling, insurance, follow_up, language, empathy, other>",
        "current_behavior": "<what the AI currently does poorly>",
        "suggested_change": "<specific wording or behavior change to make>",
        "expected_impact": "<what improvement this should cause>",
        "priority": "<high/medium/low>"
    }}
]

Focus on changes that would have the highest impact on quality scores and frustration reduction. Be specific about prompt wording changes, not vague recommendations."""


# ---------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------

def _parse_analysis_response(response_text: str) -> dict:
    """Parse Claude's analysis response into a structured dict."""
    # Strip markdown code fences if present
    text_clean = response_text.strip()
    if text_clean.startswith("```"):
        # Remove opening fence (```json or ```)
        first_newline = text_clean.index("\n")
        text_clean = text_clean[first_newline + 1:]
    if text_clean.endswith("```"):
        text_clean = text_clean[:-3].strip()

    try:
        parsed = json.loads(text_clean)
    except json.JSONDecodeError:
        logger.warning("Failed to parse analysis response as JSON, using defaults")
        return {
            "quality_score": 5,
            "missed_intents": [],
            "improvement_suggestions": ["Unable to parse AI analysis"],
            "frustration_detected": False,
            "key_phrases": [],
        }

    return {
        "quality_score": max(1, min(10, int(parsed.get("quality_score", 5)))),
        "missed_intents": parsed.get("missed_intents", [])[:10],
        "improvement_suggestions": parsed.get("improvement_suggestions", [])[:10],
        "frustration_detected": bool(parsed.get("frustration_detected", False)),
        "key_phrases": parsed.get("key_phrases", [])[:20],
    }


def _parse_suggestions_response(response_text: str) -> list[dict]:
    """Parse Claude's suggestions response into a list of suggestion dicts."""
    text_clean = response_text.strip()
    if text_clean.startswith("```"):
        first_newline = text_clean.index("\n")
        text_clean = text_clean[first_newline + 1:]
    if text_clean.endswith("```"):
        text_clean = text_clean[:-3].strip()

    try:
        parsed = json.loads(text_clean)
    except json.JSONDecodeError:
        logger.warning("Failed to parse suggestions response as JSON")
        return []

    if not isinstance(parsed, list):
        return []

    valid_priorities = {"high", "medium", "low"}
    suggestions = []
    for item in parsed[:5]:
        suggestions.append({
            "category": str(item.get("category", "other"))[:50],
            "current_behavior": str(item.get("current_behavior", ""))[:500],
            "suggested_change": str(item.get("suggested_change", ""))[:500],
            "expected_impact": str(item.get("expected_impact", ""))[:500],
            "priority": item.get("priority", "medium") if item.get("priority") in valid_priorities else "medium",
        })

    return suggestions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_top_items(items: list[str], top_n: int = 5) -> list[dict]:
    """Count frequency of items and return top N."""
    counts: dict[str, int] = {}
    for item in items:
        normalized = item.strip().lower()
        if normalized:
            counts[normalized] = counts.get(normalized, 0) + 1

    sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return [{"item": item, "count": count} for item, count in sorted_items[:top_n]]


def _generate_recommendation(
    avg_quality: float,
    quality_trend: str,
    frustration_rate: float,
    calls_analyzed: int,
) -> str:
    """Generate a human-readable recommendation based on metrics."""
    if calls_analyzed < 5:
        return (
            "Not enough data for a meaningful recommendation. "
            "Analyze at least 5 calls to get actionable insights."
        )

    parts: list[str] = []

    if avg_quality >= 8:
        parts.append("Call quality is excellent.")
    elif avg_quality >= 6:
        parts.append("Call quality is good with room for improvement.")
    elif avg_quality >= 4:
        parts.append("Call quality needs attention. Review top missed intents.")
    else:
        parts.append(
            "Call quality is critically low. Immediate prompt revision recommended."
        )

    if quality_trend == "improving":
        parts.append("Quality is trending upward.")
    elif quality_trend == "declining":
        parts.append("Quality is declining -- investigate recent changes.")
    elif quality_trend == "stable":
        parts.append("Quality has been stable.")

    if frustration_rate > 30:
        parts.append(
            f"Frustration rate of {frustration_rate}% is high. "
            "Focus on empathy and clearer communication."
        )
    elif frustration_rate > 15:
        parts.append(
            f"Frustration rate of {frustration_rate}% is moderate. "
            "Review frustrated call transcripts for patterns."
        )

    return " ".join(parts)
