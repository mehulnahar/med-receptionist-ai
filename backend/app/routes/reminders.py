"""
Appointment reminder API endpoints.

Provides endpoints for:
- Listing reminders (with filters by status, date range)
- Viewing upcoming reminders for the dashboard
- Manually scheduling reminders for an appointment
- Cancelling a reminder
- Twilio incoming SMS webhook for patient replies
"""

import logging
from datetime import datetime, timezone, date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select, and_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.appointment import Appointment
from app.models.patient import Patient
from app.models.reminder import AppointmentReminder
from app.middleware.auth import require_any_staff
from app.services.reminder_service import (
    schedule_reminders,
    cancel_reminders,
    handle_sms_reply,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ReminderResponse(BaseModel):
    id: UUID
    practice_id: UUID
    appointment_id: UUID
    patient_id: UUID
    reminder_type: str
    scheduled_for: datetime
    sent_at: datetime | None = None
    status: str
    message_content: str | None = None
    response: str | None = None
    message_sid: str | None = None
    attempts: int
    created_at: datetime
    updated_at: datetime | None = None
    # Joined fields
    patient_name: str | None = None
    appointment_date: date | None = None
    appointment_time: str | None = None

    class Config:
        from_attributes = True


class ReminderListResponse(BaseModel):
    reminders: list[ReminderResponse]
    total: int


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


def _build_reminder_response(
    reminder: AppointmentReminder,
    patient_name: str | None = None,
) -> ReminderResponse:
    """Build a ReminderResponse from a model instance."""
    appt = reminder.appointment
    return ReminderResponse(
        id=reminder.id,
        practice_id=reminder.practice_id,
        appointment_id=reminder.appointment_id,
        patient_id=reminder.patient_id,
        reminder_type=reminder.reminder_type,
        scheduled_for=reminder.scheduled_for,
        sent_at=reminder.sent_at,
        status=reminder.status,
        message_content=reminder.message_content,
        response=reminder.response,
        message_sid=reminder.message_sid,
        attempts=reminder.attempts,
        created_at=reminder.created_at,
        updated_at=reminder.updated_at,
        patient_name=patient_name or (
            f"{reminder.patient.first_name} {reminder.patient.last_name}"
            if reminder.patient else None
        ),
        appointment_date=appt.date if appt else None,
        appointment_time=appt.time.strftime("%H:%M") if appt and appt.time else None,
    )


VALID_STATUSES = {"pending", "sent", "failed", "cancelled"}


# ---------------------------------------------------------------------------
# GET /api/reminders/ -- List reminders with filters
# ---------------------------------------------------------------------------

@router.get("/", response_model=ReminderListResponse)
async def list_reminders(
    status_filter: Optional[str] = Query(None, alias="status"),
    date_from: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """List reminders for the current practice with optional filters."""
    practice_id = _ensure_practice(current_user)

    filters = [AppointmentReminder.practice_id == practice_id]

    if status_filter:
        if status_filter not in VALID_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
            )
        filters.append(AppointmentReminder.status == status_filter)

    dt_from_val = None
    dt_to_val = None

    if date_from:
        try:
            dt_from_val = date.fromisoformat(date_from)
            filters.append(
                AppointmentReminder.scheduled_for >= datetime(
                    dt_from_val.year, dt_from_val.month, dt_from_val.day, tzinfo=timezone.utc,
                )
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format. Use YYYY-MM-DD.")

    if date_to:
        try:
            from datetime import timedelta
            dt_to_val = date.fromisoformat(date_to)
            filters.append(
                AppointmentReminder.scheduled_for < datetime(
                    dt_to_val.year, dt_to_val.month, dt_to_val.day, tzinfo=timezone.utc,
                ) + timedelta(days=1)
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format. Use YYYY-MM-DD.")

    # Validate date ordering and cap range
    if dt_from_val and dt_to_val:
        if dt_from_val > dt_to_val:
            raise HTTPException(status_code=400, detail="date_from cannot be after date_to.")
        if (dt_to_val - dt_from_val).days > 365:
            raise HTTPException(status_code=400, detail="Date range cannot exceed 365 days.")

    # Count
    count_query = select(func.count(AppointmentReminder.id)).where(and_(*filters))
    total = (await db.execute(count_query)).scalar_one()

    # Paginated query
    query = (
        select(AppointmentReminder)
        .where(and_(*filters))
        .order_by(desc(AppointmentReminder.scheduled_for))
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    reminders = result.scalars().all()

    return ReminderListResponse(
        reminders=[_build_reminder_response(r) for r in reminders],
        total=total,
    )


# ---------------------------------------------------------------------------
# GET /api/reminders/upcoming -- Upcoming reminders for the dashboard
# ---------------------------------------------------------------------------

@router.get("/upcoming", response_model=ReminderListResponse)
async def upcoming_reminders(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """
    Get upcoming pending reminders for the dashboard.

    Returns reminders that are scheduled but not yet sent, ordered by
    scheduled_for ascending (soonest first).
    """
    practice_id = _ensure_practice(current_user)

    filters = [
        AppointmentReminder.practice_id == practice_id,
        AppointmentReminder.status == "pending",
    ]

    count_query = select(func.count(AppointmentReminder.id)).where(and_(*filters))
    total = (await db.execute(count_query)).scalar_one()

    query = (
        select(AppointmentReminder)
        .where(and_(*filters))
        .order_by(AppointmentReminder.scheduled_for.asc())
        .limit(limit)
    )
    result = await db.execute(query)
    reminders = result.scalars().all()

    return ReminderListResponse(
        reminders=[_build_reminder_response(r) for r in reminders],
        total=total,
    )


# ---------------------------------------------------------------------------
# POST /api/reminders/schedule/{appointment_id} -- Manually schedule reminders
# ---------------------------------------------------------------------------

@router.post("/schedule/{appointment_id}", response_model=list[ReminderResponse])
async def schedule_reminders_endpoint(
    appointment_id: UUID,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """
    Manually schedule (or reschedule) reminders for an appointment.

    Cancels any existing pending reminders and creates new ones.
    """
    practice_id = _ensure_practice(current_user)

    # Verify appointment exists and belongs to this practice
    appt_result = await db.execute(
        select(Appointment).where(
            and_(
                Appointment.id == appointment_id,
                Appointment.practice_id == practice_id,
            )
        )
    )
    appointment = appt_result.scalar_one_or_none()

    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )

    if appointment.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot schedule reminders for a cancelled appointment",
        )

    # Cancel existing pending reminders first
    await cancel_reminders(db, appointment_id)

    # Schedule new reminders
    created = await schedule_reminders(db, appointment)

    if not created:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No reminders could be scheduled (appointment may be too soon or patient has no phone)",
        )

    return [_build_reminder_response(r) for r in created]


# ---------------------------------------------------------------------------
# DELETE /api/reminders/{reminder_id} -- Cancel a single reminder
# ---------------------------------------------------------------------------

@router.delete("/{reminder_id}")
async def cancel_reminder_endpoint(
    reminder_id: UUID,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a single pending reminder."""
    practice_id = _ensure_practice(current_user)

    result = await db.execute(
        select(AppointmentReminder).where(
            and_(
                AppointmentReminder.id == reminder_id,
                AppointmentReminder.practice_id == practice_id,
            )
        )
    )
    reminder = result.scalar_one_or_none()

    if not reminder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reminder not found",
        )

    if reminder.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel a reminder with status '{reminder.status}'",
        )

    reminder.status = "cancelled"
    await db.flush()
    await db.commit()

    return {"status": "ok", "message": "Reminder cancelled"}


# ---------------------------------------------------------------------------
# POST /api/reminders/twilio-reply -- Twilio incoming SMS webhook
# ---------------------------------------------------------------------------

@router.post("/twilio-reply")
async def twilio_sms_reply(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Webhook endpoint for Twilio incoming SMS replies.

    Twilio sends form-encoded data with fields: From, Body, MessageSid, etc.
    Validates X-Twilio-Signature to prevent forged requests (e.g. fake CANCEL).

    Processes patient replies (CONFIRM, CANCEL, RESCHEDULE) and returns
    a TwiML response to send a reply back to the patient.
    """
    try:
        # Verify Twilio signature to prevent forged appointment cancellations
        from app.config import get_settings
        _settings = get_settings()
        _twilio_auth = _settings.TWILIO_AUTH_TOKEN
        form_data = await request.form()

        if not _twilio_auth:
            logger.error("twilio_sms_reply: TWILIO_AUTH_TOKEN not configured — rejecting request")
            return PlainTextResponse(
                content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                media_type="application/xml",
                status_code=500,
            )

        try:
            from twilio.request_validator import RequestValidator
            validator = RequestValidator(_twilio_auth)
            signature = request.headers.get("X-Twilio-Signature", "")
            url = str(request.url)
            params = {k: v for k, v in form_data.items()}
            if not validator.validate(url, params, signature):
                logger.warning(
                    "twilio_sms_reply: invalid Twilio signature from %s",
                    request.client.host if request.client else "unknown",
                )
                return PlainTextResponse(
                    content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                    media_type="application/xml",
                    status_code=403,
                )
        except ImportError:
            logger.error("twilio_sms_reply: twilio package not installed — cannot validate signature")
            return PlainTextResponse(
                content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                media_type="application/xml",
                status_code=500,
            )

        from_number = form_data.get("From", "")
        body = form_data.get("Body", "")
        message_sid = form_data.get("MessageSid", "")

        logger.info(
            "twilio_sms_reply: received SMS from=%s body='%s' sid=%s",
            from_number, body[:100], message_sid,
        )

        if not from_number or not body:
            logger.warning("twilio_sms_reply: missing From or Body in request")
            return PlainTextResponse(
                content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                media_type="application/xml",
            )

        # Process the reply
        result = await handle_sms_reply(db, from_number, body)

        # Build TwiML response to reply to the patient
        from xml.sax.saxutils import escape as xml_escape
        reply_message = result.get("reply_message", "")
        if reply_message:
            safe_msg = xml_escape(reply_message)
            twiml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f"<Response><Message>{safe_msg}</Message></Response>"
            )
        else:
            twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'

        return PlainTextResponse(content=twiml, media_type="application/xml")

    except Exception as e:
        logger.exception("twilio_sms_reply: error handling incoming SMS: %s", e)
        return PlainTextResponse(
            content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="application/xml",
        )
