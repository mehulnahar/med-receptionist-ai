"""
Enhanced reminder API routes.

Provides endpoints for:
- GET  /enhanced-reminders/status/{appointment_id}  -- reminder status per appointment
- POST /enhanced-reminders/schedule/{appointment_id} -- manually schedule reminders
- POST /enhanced-reminders/webhook/response           -- Twilio inbound SMS webhook
- GET  /enhanced-reminders/stats                      -- reminder statistics (admin)
"""

import logging
from datetime import datetime, date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.appointment import Appointment
from app.models.user import User
from app.middleware.auth import get_current_user, require_any_staff, require_practice_admin
from app.services.enhanced_reminders import (
    schedule_appointment_reminders,
    handle_reminder_response,
    get_reminder_stats,
    get_reminders_for_appointment,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ReminderStatusItem(BaseModel):
    id: UUID
    reminder_type: str
    scheduled_for: datetime
    sent_at: datetime | None = None
    status: str
    message_content: str | None = None
    response: str | None = None
    attempts: int
    created_at: datetime

    class Config:
        from_attributes = True


class ReminderStatusResponse(BaseModel):
    appointment_id: UUID
    reminders: list[ReminderStatusItem]
    total: int


class ScheduleResponse(BaseModel):
    appointment_id: UUID
    scheduled: list[dict]
    message: str


class WebhookResponseResult(BaseModel):
    action_taken: str
    appointment_id: str | None = None


class StatsResponse(BaseModel):
    total: int
    pending: int
    sent: int
    failed: int
    cancelled: int
    confirmed_by_patient: int
    cancelled_by_patient: int
    delivery_rate: float
    confirmation_rate: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_practice(user: User) -> UUID:
    """Extract and validate the user's practice_id."""
    if not user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )
    return user.practice_id


# ---------------------------------------------------------------------------
# GET /enhanced-reminders/status/{appointment_id}
# ---------------------------------------------------------------------------

@router.get(
    "/status/{appointment_id}",
    response_model=ReminderStatusResponse,
    summary="Get reminder status for an appointment",
)
async def get_appointment_reminder_status(
    appointment_id: UUID,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Return all reminder records for a specific appointment.

    Accessible by any authenticated staff member (secretary, practice_admin,
    super_admin).
    """
    practice_id = _ensure_practice(current_user)

    # Verify the appointment belongs to this practice
    appt_check = await db.execute(
        select(Appointment.id).where(
            and_(
                Appointment.id == appointment_id,
                Appointment.practice_id == practice_id,
            )
        )
    )
    if not appt_check.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )

    reminders = await get_reminders_for_appointment(db, appointment_id, practice_id)

    return ReminderStatusResponse(
        appointment_id=appointment_id,
        reminders=[
            ReminderStatusItem(
                id=r.id,
                reminder_type=r.reminder_type,
                scheduled_for=r.scheduled_for,
                sent_at=r.sent_at,
                status=r.status,
                message_content=r.message_content,
                response=r.response,
                attempts=r.attempts,
                created_at=r.created_at,
            )
            for r in reminders
        ],
        total=len(reminders),
    )


# ---------------------------------------------------------------------------
# POST /enhanced-reminders/schedule/{appointment_id}
# ---------------------------------------------------------------------------

@router.post(
    "/schedule/{appointment_id}",
    response_model=ScheduleResponse,
    summary="Manually schedule enhanced reminders",
)
async def schedule_reminders_endpoint(
    appointment_id: UUID,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger the enhanced reminder scheduling for an appointment.

    This creates up to three reminder records (confirmation, 24-hour, 2-hour).
    If reminders already exist for the same appointment and time, duplicates
    are silently skipped.

    Accessible by any authenticated staff member.
    """
    practice_id = _ensure_practice(current_user)

    # Verify the appointment exists and is active
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

    if appointment.status == "no_show":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot schedule reminders for a no-show appointment",
        )

    scheduled = await schedule_appointment_reminders(db, practice_id, appointment_id)

    if not scheduled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No reminders could be scheduled. The appointment may be in the past "
                "or the patient has no phone number on file."
            ),
        )

    await db.commit()

    return ScheduleResponse(
        appointment_id=appointment_id,
        scheduled=scheduled,
        message=f"Scheduled {len(scheduled)} reminder(s) for appointment {appointment_id}",
    )


# ---------------------------------------------------------------------------
# POST /enhanced-reminders/webhook/response -- Twilio inbound SMS webhook
# ---------------------------------------------------------------------------

@router.post(
    "/webhook/response",
    summary="Twilio inbound SMS webhook for reminder responses",
)
async def twilio_response_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle inbound SMS replies from patients.

    This endpoint is called by Twilio when a patient replies to a reminder
    SMS.  It is **public** (no auth) because Twilio cannot send a Bearer
    token -- instead we validate the ``X-Twilio-Signature`` header to
    prevent forged requests.

    Processes CONFIRM/CANCEL/RESCHEDULE keywords and returns a TwiML
    ``<Response>`` so Twilio sends an acknowledgement back to the patient.
    """
    try:
        # --- Validate Twilio signature ---
        from app.config import get_settings
        _settings = get_settings()
        twilio_auth = _settings.TWILIO_AUTH_TOKEN

        form_data = await request.form()

        if not twilio_auth:
            logger.error(
                "twilio_response_webhook: TWILIO_AUTH_TOKEN not configured",
            )
            return PlainTextResponse(
                content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                media_type="application/xml",
                status_code=500,
            )

        try:
            from twilio.request_validator import RequestValidator
            validator = RequestValidator(twilio_auth)
            signature = request.headers.get("X-Twilio-Signature", "")
            url = str(request.url)
            params = {k: v for k, v in form_data.items()}
            if not validator.validate(url, params, signature):
                logger.warning(
                    "twilio_response_webhook: invalid signature from %s",
                    request.client.host if request.client else "unknown",
                )
                return PlainTextResponse(
                    content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                    media_type="application/xml",
                    status_code=403,
                )
        except ImportError:
            logger.error(
                "twilio_response_webhook: twilio package not installed",
            )
            return PlainTextResponse(
                content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                media_type="application/xml",
                status_code=500,
            )

        # --- Extract fields ---
        from_number = form_data.get("From", "")
        body = form_data.get("Body", "")
        message_sid = form_data.get("MessageSid", "")

        logger.info(
            "twilio_response_webhook: from=%s body='%s' sid=%s",
            from_number, body[:100], message_sid,
        )

        if not from_number or not body:
            return PlainTextResponse(
                content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                media_type="application/xml",
            )

        # --- Process the reply ---
        result = await handle_reminder_response(db, from_number, body)

        # --- Build TwiML reply ---
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
        logger.exception(
            "twilio_response_webhook: unhandled error: %s", e,
        )
        return PlainTextResponse(
            content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="application/xml",
        )


# ---------------------------------------------------------------------------
# GET /enhanced-reminders/stats -- Reminder statistics (practice_admin)
# ---------------------------------------------------------------------------

@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Get reminder statistics for the practice",
)
async def reminder_stats(
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate reminder statistics for the current practice.

    Includes delivery rates, confirmation rates, and counts by status.
    Restricted to practice_admin and super_admin roles.
    """
    practice_id = _ensure_practice(current_user)
    stats = await get_reminder_stats(db, practice_id)
    return StatsResponse(**stats)
