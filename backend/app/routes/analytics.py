"""Analytics endpoints for the dashboard — call volume, peak hours, booking
conversion, call outcomes, appointment types, and combined overview."""

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_, case, extract, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.call import Call
from app.models.appointment import Appointment
from app.models.appointment_type import AppointmentType
from app.models.patient import Patient
from app.models.user import User
from app.middleware.auth import require_any_staff

logger = logging.getLogger(__name__)

router = APIRouter()

# Outcomes that count as "missed"
MISSED_OUTCOMES = {
    "customer-did-not-answer",
    "customer-busy",
    "assistant-error",
    "phone-call-provider-closed-websocket",
}

# Caller intents that indicate booking intent
BOOKING_INTENTS = {"book", "new_patient", "schedule"}


def _default_date_range(
    from_date: Optional[str],
    to_date: Optional[str],
    days: int = 30,
) -> tuple[date, date]:
    """Parse optional date strings into a (start, end) date range.

    Falls back to the last *days* days when values are not provided.
    """
    end = date.fromisoformat(to_date) if to_date else date.today()
    start = date.fromisoformat(from_date) if from_date else end - timedelta(days=days)
    return start, end


def _ensure_practice(user: User):
    """Return the user's practice_id or raise 400."""
    if not user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )
    return user.practice_id


# ---------------------------------------------------------------------------
# 1. GET /call-volume
# ---------------------------------------------------------------------------


@router.get("/call-volume")
async def get_call_volume(
    from_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Daily call volumes for the requested date range (default last 30 days)."""
    practice_id = _ensure_practice(current_user)
    start, end = _default_date_range(from_date, to_date)

    call_date = cast(Call.started_at, Date).label("call_date")

    stmt = (
        select(
            call_date,
            func.count().label("total"),
            func.count()
            .filter(Call.direction == "inbound")
            .label("inbound"),
            func.count()
            .filter(Call.direction == "outbound")
            .label("outbound"),
            func.count()
            .filter(Call.outcome.in_(MISSED_OUTCOMES))
            .label("missed"),
        )
        .where(
            and_(
                Call.practice_id == practice_id,
                cast(Call.started_at, Date) >= start,
                cast(Call.started_at, Date) <= end,
            )
        )
        .group_by(call_date)
        .order_by(call_date)
    )

    result = await db.execute(stmt)
    rows = result.all()

    data = [
        {
            "date": row.call_date.isoformat(),
            "total": row.total,
            "inbound": row.inbound,
            "outbound": row.outbound,
            "missed": row.missed,
        }
        for row in rows
    ]

    total_calls = sum(r["total"] for r in data)
    num_days = len(data) or 1

    return {
        "data": data,
        "summary": {
            "total_calls": total_calls,
            "avg_daily": round(total_calls / num_days, 1),
        },
    }


# ---------------------------------------------------------------------------
# 2. GET /peak-hours
# ---------------------------------------------------------------------------


@router.get("/peak-hours")
async def get_peak_hours(
    from_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Call counts by hour of day (0-23) for a date range."""
    practice_id = _ensure_practice(current_user)
    start, end = _default_date_range(from_date, to_date)

    hour_col = extract("hour", Call.started_at).label("hour")

    stmt = (
        select(hour_col, func.count().label("count"))
        .where(
            and_(
                Call.practice_id == practice_id,
                cast(Call.started_at, Date) >= start,
                cast(Call.started_at, Date) <= end,
            )
        )
        .group_by(hour_col)
        .order_by(hour_col)
    )

    result = await db.execute(stmt)
    rows = result.all()

    # Build a full 0-23 hour map, filling missing hours with 0
    hour_map = {int(row.hour): row.count for row in rows}
    data = [{"hour": h, "count": hour_map.get(h, 0)} for h in range(24)]

    peak = max(data, key=lambda d: d["count"])

    return {
        "data": data,
        "peak_hour": peak["hour"],
        "peak_count": peak["count"],
    }


# ---------------------------------------------------------------------------
# 3. GET /booking-conversion
# ---------------------------------------------------------------------------


@router.get("/booking-conversion")
async def get_booking_conversion(
    from_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Booking conversion funnel data."""
    practice_id = _ensure_practice(current_user)
    start, end = _default_date_range(from_date, to_date)

    # Total calls in range
    total_calls_stmt = (
        select(func.count())
        .select_from(Call)
        .where(
            and_(
                Call.practice_id == practice_id,
                cast(Call.started_at, Date) >= start,
                cast(Call.started_at, Date) <= end,
            )
        )
    )
    total_calls = (await db.execute(total_calls_stmt)).scalar() or 0

    # Calls with booking intent
    intent_stmt = (
        select(func.count())
        .select_from(Call)
        .where(
            and_(
                Call.practice_id == practice_id,
                cast(Call.started_at, Date) >= start,
                cast(Call.started_at, Date) <= end,
                Call.caller_intent.in_(BOOKING_INTENTS),
            )
        )
    )
    calls_with_intent_book = (await db.execute(intent_stmt)).scalar() or 0

    # Appointments booked by AI in range
    booked_stmt = (
        select(func.count())
        .select_from(Appointment)
        .where(
            and_(
                Appointment.practice_id == practice_id,
                Appointment.booked_by == "ai",
                Appointment.created_at >= datetime.combine(start, datetime.min.time()),
                Appointment.created_at <= datetime.combine(end, datetime.max.time()),
            )
        )
    )
    appointments_booked = (await db.execute(booked_stmt)).scalar() or 0

    # Confirmed appointments
    confirmed_stmt = (
        select(func.count())
        .select_from(Appointment)
        .where(
            and_(
                Appointment.practice_id == practice_id,
                Appointment.booked_by == "ai",
                Appointment.status == "confirmed",
                Appointment.created_at >= datetime.combine(start, datetime.min.time()),
                Appointment.created_at <= datetime.combine(end, datetime.max.time()),
            )
        )
    )
    appointments_confirmed = (await db.execute(confirmed_stmt)).scalar() or 0

    # Completed appointments
    completed_stmt = (
        select(func.count())
        .select_from(Appointment)
        .where(
            and_(
                Appointment.practice_id == practice_id,
                Appointment.booked_by == "ai",
                Appointment.status == "completed",
                Appointment.created_at >= datetime.combine(start, datetime.min.time()),
                Appointment.created_at <= datetime.combine(end, datetime.max.time()),
            )
        )
    )
    appointments_completed = (await db.execute(completed_stmt)).scalar() or 0

    conversion_rate = round(
        (appointments_booked / total_calls * 100) if total_calls else 0, 1
    )
    confirmation_rate = round(
        (appointments_confirmed / appointments_booked * 100)
        if appointments_booked
        else 0,
        1,
    )

    return {
        "total_calls": total_calls,
        "calls_with_intent_book": calls_with_intent_book,
        "appointments_booked": appointments_booked,
        "appointments_confirmed": appointments_confirmed,
        "appointments_completed": appointments_completed,
        "conversion_rate": conversion_rate,
        "confirmation_rate": confirmation_rate,
    }


# ---------------------------------------------------------------------------
# 4. GET /call-outcomes
# ---------------------------------------------------------------------------


@router.get("/call-outcomes")
async def get_call_outcomes(
    from_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Breakdown of call intents, sentiments, outcomes, and languages."""
    practice_id = _ensure_practice(current_user)
    start, end = _default_date_range(from_date, to_date)

    base_filter = and_(
        Call.practice_id == practice_id,
        cast(Call.started_at, Date) >= start,
        cast(Call.started_at, Date) <= end,
    )

    async def _grouped(column):
        stmt = (
            select(column, func.count().label("count"))
            .where(and_(base_filter, column.isnot(None)))
            .group_by(column)
            .order_by(func.count().desc())
        )
        rows = (await db.execute(stmt)).all()
        return rows

    intent_rows = await _grouped(Call.caller_intent)
    sentiment_rows = await _grouped(Call.caller_sentiment)
    outcome_rows = await _grouped(Call.outcome)
    language_rows = await _grouped(Call.language)

    return {
        "intents": [
            {"intent": row.caller_intent, "count": row.count}
            for row in intent_rows
        ],
        "sentiments": [
            {"sentiment": row.caller_sentiment, "count": row.count}
            for row in sentiment_rows
        ],
        "outcomes": [
            {"outcome": row.outcome, "count": row.count}
            for row in outcome_rows
        ],
        "languages": [
            {"language": row.language, "count": row.count}
            for row in language_rows
        ],
    }


# ---------------------------------------------------------------------------
# 5. GET /appointment-types
# ---------------------------------------------------------------------------


@router.get("/appointment-types")
async def get_appointment_type_stats(
    from_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Appointment type distribution for a date range."""
    practice_id = _ensure_practice(current_user)
    start, end = _default_date_range(from_date, to_date)

    stmt = (
        select(
            AppointmentType.name.label("type_name"),
            func.count().label("count"),
        )
        .join(
            Appointment,
            Appointment.appointment_type_id == AppointmentType.id,
        )
        .where(
            and_(
                Appointment.practice_id == practice_id,
                Appointment.date >= start,
                Appointment.date <= end,
            )
        )
        .group_by(AppointmentType.name)
        .order_by(func.count().desc())
    )

    result = await db.execute(stmt)
    rows = result.all()

    total = sum(row.count for row in rows) or 1

    data = [
        {
            "type_name": row.type_name,
            "count": row.count,
            "percentage": round(row.count / total * 100, 1),
        }
        for row in rows
    ]

    return {"data": data}


# ---------------------------------------------------------------------------
# 6. GET /overview
# ---------------------------------------------------------------------------


@router.get("/overview")
async def get_overview(
    period: Optional[str] = Query(
        "month",
        description="Time period: today, week, or month",
    ),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Combined overview for the dashboard header."""
    practice_id = _ensure_practice(current_user)

    today = date.today()
    if period == "today":
        start = today
    elif period == "week":
        start = today - timedelta(days=7)
    else:
        period = "month"
        start = today - timedelta(days=30)
    end = today

    # --- Calls ---
    call_filter = and_(
        Call.practice_id == practice_id,
        cast(Call.started_at, Date) >= start,
        cast(Call.started_at, Date) <= end,
    )

    calls_stmt = select(
        func.count().label("total"),
        func.count().filter(Call.outcome.in_(MISSED_OUTCOMES)).label("missed"),
        func.coalesce(func.avg(Call.duration_seconds), 0).label("avg_duration"),
        func.coalesce(func.sum(Call.vapi_cost), 0).label("total_cost"),
    ).where(call_filter)

    calls_row = (await db.execute(calls_stmt)).one()

    # --- Appointments ---
    appt_filter = and_(
        Appointment.practice_id == practice_id,
        Appointment.date >= start,
        Appointment.date <= end,
    )

    appt_stmt = select(
        func.count().label("booked"),
        func.count().filter(Appointment.status == "confirmed").label("confirmed"),
        func.count().filter(Appointment.status == "cancelled").label("cancelled"),
        func.count().filter(Appointment.status == "no_show").label("no_show"),
    ).where(appt_filter)

    appt_row = (await db.execute(appt_stmt)).one()

    # --- Patients ---
    patient_filter = and_(
        Patient.practice_id == practice_id,
        Patient.created_at >= datetime.combine(start, datetime.min.time()),
        Patient.created_at <= datetime.combine(end, datetime.max.time()),
    )

    new_patients_stmt = (
        select(func.count())
        .select_from(Patient)
        .where(and_(patient_filter, Patient.is_new.is_(True)))
    )
    new_patients = (await db.execute(new_patients_stmt)).scalar() or 0

    returning_patients_stmt = (
        select(func.count())
        .select_from(Patient)
        .where(and_(patient_filter, Patient.is_new.is_(False)))
    )
    returning_patients = (await db.execute(returning_patients_stmt)).scalar() or 0

    # --- AI performance ---
    total_calls = calls_row.total or 0
    missed_calls = calls_row.missed or 0
    handled_calls = total_calls - missed_calls
    success_rate = round(
        (handled_calls / total_calls * 100) if total_calls else 0, 1
    )
    transfer_rate = round(
        (missed_calls / total_calls * 100) if total_calls else 0, 1
    )

    return {
        "period": period,
        "calls": {
            "total": total_calls,
            "missed": missed_calls,
            "avg_duration": round(float(calls_row.avg_duration)),
            "total_cost": round(float(calls_row.total_cost), 2),
        },
        "appointments": {
            "booked": appt_row.booked,
            "confirmed": appt_row.confirmed,
            "cancelled": appt_row.cancelled,
            "no_show": appt_row.no_show,
        },
        "patients": {
            "new_patients": new_patients,
            "returning": returning_patients,
        },
        "ai_performance": {
            "success_rate": success_rate,
            "avg_call_duration": round(float(calls_row.avg_duration)),
            "transfer_rate": transfer_rate,
        },
    }
