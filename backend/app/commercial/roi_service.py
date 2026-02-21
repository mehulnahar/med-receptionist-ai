"""
ROI Dashboard Service — calculates and serves return-on-investment metrics.

This is the most important commercial feature — it SELLS the product.
Shows practices exactly how much money the AI is saving them.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select, func, and_, text, case
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Default values when practice hasn't configured ROI settings
DEFAULT_STAFF_HOURLY_COST = Decimal("25.00")
DEFAULT_AVG_APPOINTMENT_VALUE = Decimal("150.00")
DEFAULT_HUMAN_RECEPTIONIST_MONTHLY = Decimal("3500.00")
DEFAULT_AVG_CALL_DURATION_MIN = Decimal("4.50")
DEFAULT_NO_SHOW_REDUCTION = Decimal("0.40")  # 40% reduction


async def get_roi_config(db: AsyncSession, practice_id: UUID) -> dict:
    """Fetch ROI configuration for a practice, with defaults."""
    result = await db.execute(
        text("SELECT * FROM roi_config WHERE practice_id = :pid"),
        {"pid": str(practice_id)},
    )
    row = result.fetchone()

    if row:
        return {
            "staff_hourly_cost": Decimal(str(row.staff_hourly_cost or DEFAULT_STAFF_HOURLY_COST)),
            "avg_appointment_value": Decimal(str(row.avg_appointment_value or DEFAULT_AVG_APPOINTMENT_VALUE)),
            "human_receptionist_monthly_cost": Decimal(str(row.human_receptionist_monthly_cost or DEFAULT_HUMAN_RECEPTIONIST_MONTHLY)),
            "avg_call_duration_minutes": Decimal(str(row.avg_call_duration_minutes or DEFAULT_AVG_CALL_DURATION_MIN)),
            "no_show_reduction_rate": Decimal(str(row.no_show_reduction_rate or DEFAULT_NO_SHOW_REDUCTION)),
        }

    return {
        "staff_hourly_cost": DEFAULT_STAFF_HOURLY_COST,
        "avg_appointment_value": DEFAULT_AVG_APPOINTMENT_VALUE,
        "human_receptionist_monthly_cost": DEFAULT_HUMAN_RECEPTIONIST_MONTHLY,
        "avg_call_duration_minutes": DEFAULT_AVG_CALL_DURATION_MIN,
        "no_show_reduction_rate": DEFAULT_NO_SHOW_REDUCTION,
    }


async def get_roi_summary(
    db: AsyncSession,
    practice_id: UUID,
    period: str = "month",  # "week" or "month"
) -> dict:
    """Calculate comprehensive ROI metrics for a practice.

    Returns metrics that prove the AI's value:
    - Calls handled by AI
    - AI resolution rate
    - Staff hours saved
    - Money saved vs hiring human
    - No-shows prevented
    - Revenue protected
    """
    config = await get_roi_config(db, practice_id)

    # Date range
    now = datetime.now(timezone.utc)
    if period == "week":
        start_date = now - timedelta(days=7)
        label = "This Week"
    else:
        start_date = now - timedelta(days=30)
        label = "This Month"

    # 1. Total calls handled
    calls_result = await db.execute(text("""
        SELECT
            COUNT(*) as total_calls,
            COUNT(*) FILTER (WHERE status = 'completed') as completed_calls,
            COUNT(*) FILTER (WHERE status = 'transferred') as transferred_calls,
            AVG(duration_seconds) FILTER (WHERE duration_seconds > 0) as avg_duration
        FROM calls
        WHERE practice_id = :pid AND started_at >= :start
    """), {"pid": str(practice_id), "start": start_date})
    calls_row = calls_result.fetchone()

    total_calls = calls_row.total_calls or 0
    completed_calls = calls_row.completed_calls or 0
    transferred_calls = calls_row.transferred_calls or 0
    avg_duration = Decimal(str(calls_row.avg_duration or 0))

    # 2. AI resolution rate (completed without transfer)
    ai_resolved = completed_calls
    resolution_rate = (
        (Decimal(str(ai_resolved)) / Decimal(str(total_calls)) * 100)
        if total_calls > 0 else Decimal("0")
    )

    # 3. Appointments booked by AI
    appts_result = await db.execute(text("""
        SELECT COUNT(*) as ai_booked
        FROM appointments
        WHERE practice_id = :pid
            AND booked_by = 'ai'
            AND created_at >= :start
    """), {"pid": str(practice_id), "start": start_date})
    ai_booked = appts_result.scalar() or 0

    # 4. Staff hours saved
    call_hours = (
        Decimal(str(total_calls)) * config["avg_call_duration_minutes"] / Decimal("60")
    )
    staff_cost_saved = call_hours * config["staff_hourly_cost"]

    # 5. Reminders sent and no-shows prevented
    reminders_result = await db.execute(text("""
        SELECT COUNT(*) as sent
        FROM reminders
        WHERE practice_id = :pid
            AND status = 'sent'
            AND sent_at >= :start
    """), {"pid": str(practice_id), "start": start_date})
    reminders_sent = reminders_result.scalar() or 0

    # Count actual no-shows in the period
    noshow_result = await db.execute(text("""
        SELECT COUNT(*) as noshows
        FROM appointments
        WHERE practice_id = :pid
            AND status = 'no_show'
            AND date >= :start_date
    """), {"pid": str(practice_id), "start_date": start_date.date()})
    actual_noshows = noshow_result.scalar() or 0

    # Estimated no-shows prevented = reminders × reduction rate
    noshows_prevented = int(
        Decimal(str(reminders_sent)) * config["no_show_reduction_rate"]
    )
    revenue_protected = Decimal(str(noshows_prevented)) * config["avg_appointment_value"]

    # 6. Insurance verifications
    verif_result = await db.execute(text("""
        SELECT
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE status = 'success') as successful
        FROM insurance_verifications
        WHERE practice_id = :pid AND verified_at >= :start
    """), {"pid": str(practice_id), "start": start_date})
    verif_row = verif_result.fetchone()
    total_verifications = verif_row.total or 0
    successful_verifications = verif_row.successful or 0

    # 7. Total estimated savings
    ai_monthly_cost = Decimal("799")  # Base plan cost
    human_cost = config["human_receptionist_monthly_cost"]
    monthly_savings = human_cost - ai_monthly_cost + staff_cost_saved + revenue_protected

    # 8. Patient satisfaction (from surveys)
    survey_result = await db.execute(text("""
        SELECT AVG(score) as avg_score, COUNT(*) as total
        FROM call_surveys
        WHERE practice_id = :pid AND responded_at >= :start
    """), {"pid": str(practice_id), "start": start_date})
    survey_row = survey_result.fetchone()
    avg_satisfaction = float(survey_row.avg_score or 0)
    survey_count = survey_row.total or 0

    return {
        "period": label,
        "period_start": start_date.isoformat(),
        "period_end": now.isoformat(),
        "calls": {
            "total": total_calls,
            "ai_resolved": ai_resolved,
            "transferred": transferred_calls,
            "resolution_rate": round(float(resolution_rate), 1),
            "avg_duration_seconds": round(float(avg_duration), 0),
        },
        "appointments": {
            "ai_booked": ai_booked,
        },
        "savings": {
            "staff_hours_saved": round(float(call_hours), 1),
            "staff_cost_saved": round(float(staff_cost_saved), 2),
            "noshows_prevented": noshows_prevented,
            "revenue_protected": round(float(revenue_protected), 2),
            "estimated_monthly_savings": round(float(monthly_savings), 2),
            "vs_human_receptionist": round(float(human_cost), 2),
            "ai_monthly_cost": round(float(ai_monthly_cost), 2),
        },
        "insurance": {
            "total_verifications": total_verifications,
            "successful": successful_verifications,
        },
        "reminders": {
            "sent": reminders_sent,
        },
        "satisfaction": {
            "average_score": round(avg_satisfaction, 1),
            "total_surveys": survey_count,
        },
    }


async def get_roi_trends(
    db: AsyncSession,
    practice_id: UUID,
    weeks: int = 8,
) -> list[dict]:
    """Get weekly trend data for charts."""
    trends = []
    now = datetime.now(timezone.utc)

    for i in range(weeks - 1, -1, -1):
        week_end = now - timedelta(weeks=i)
        week_start = week_end - timedelta(days=7)

        # Calls this week
        calls_result = await db.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'completed') as resolved
            FROM calls
            WHERE practice_id = :pid
                AND started_at >= :start
                AND started_at < :end
        """), {
            "pid": str(practice_id),
            "start": week_start,
            "end": week_end,
        })
        row = calls_result.fetchone()

        # Appointments this week
        appts_result = await db.execute(text("""
            SELECT COUNT(*) FROM appointments
            WHERE practice_id = :pid
                AND booked_by = 'ai'
                AND created_at >= :start
                AND created_at < :end
        """), {
            "pid": str(practice_id),
            "start": week_start,
            "end": week_end,
        })
        ai_booked = appts_result.scalar() or 0

        total_calls = row.total or 0
        resolved = row.resolved or 0
        rate = round((resolved / total_calls * 100) if total_calls > 0 else 0, 1)

        trends.append({
            "week_start": week_start.date().isoformat(),
            "week_end": week_end.date().isoformat(),
            "total_calls": total_calls,
            "ai_resolved": resolved,
            "resolution_rate": rate,
            "ai_booked_appointments": ai_booked,
        })

    return trends
