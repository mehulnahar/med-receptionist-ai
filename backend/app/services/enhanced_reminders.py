"""
Enhanced multi-stage appointment reminder system.

Extends the base reminder service with:
- Four reminder stages: booking confirmation, 24-hour, 2-hour, no-show follow-up
- Bilingual templates (EN/ES) resolved from patient.language_preference
- Inbound SMS response handling (CONFIRM/CANCEL/RESCHEDULE keywords)
- No-show follow-up detection and outreach
- Waitlist trigger on patient cancellation via SMS

All database operations are practice-scoped. SMS delivery is delegated to the
existing sms_service.send_sms / get_twilio_credentials helpers.
"""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, and_, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.appointment import Appointment
from app.models.patient import Patient
from app.models.practice import Practice
from app.models.reminder import AppointmentReminder
from app.services.sms_service import (
    get_twilio_credentials,
    send_sms,
    format_appointment_datetime,
)

logger = logging.getLogger(__name__)

# Maximum send attempts before marking a reminder as permanently failed
MAX_SEND_ATTEMPTS = 3

# ---------------------------------------------------------------------------
# Bilingual message templates
# ---------------------------------------------------------------------------
# Each stage has EN and ES variants.  Placeholders are filled at schedule time
# (confirmation, 24h, 2h) or at send time (no-show) so the stored message_content
# is always a rendered, ready-to-send string.

TEMPLATES = {
    "confirmation": {
        "en": (
            "Your appointment with {practice_name} on {date} at {time} is confirmed! "
            "Reply CANCEL if you need to cancel."
        ),
        "es": (
            "Su cita con {practice_name} el {date} a las {time} esta confirmada! "
            "Responda CANCELAR si necesita cancelar."
        ),
    },
    "24h": {
        "en": (
            "Reminder: You have an appointment with {practice_name} tomorrow at {time}. "
            "Reply CONFIRM to confirm or CANCEL to cancel."
        ),
        "es": (
            "Recordatorio: Tiene una cita con {practice_name} manana a las {time}. "
            "Responda CONFIRMAR para confirmar o CANCELAR para cancelar."
        ),
    },
    "2h": {
        "en": (
            "Your appointment with {practice_name} is in 2 hours at {time}. "
            "See you soon!"
        ),
        "es": (
            "Su cita con {practice_name} es en 2 horas a las {time}. "
            "Nos vemos pronto!"
        ),
    },
    "no_show": {
        "en": (
            "We missed you at {practice_name} today. "
            "Would you like to reschedule? Reply YES or call {phone}."
        ),
        "es": (
            "Lo extranamos en {practice_name} hoy. "
            "Desea reprogramar? Responda SI o llame al {phone}."
        ),
    },
}


def _render_template(stage: str, language: str, variables: dict) -> str:
    """Render a template for *stage* in the given *language*.

    Falls back to English if the language is not available.
    """
    stage_templates = TEMPLATES.get(stage, TEMPLATES["confirmation"])
    template = stage_templates.get(language) or stage_templates["en"]
    try:
        return template.format_map(_SafeDict(variables))
    except Exception:
        # Belt-and-suspenders: manual replacement if .format_map fails
        rendered = template
        for key, val in variables.items():
            rendered = rendered.replace(f"{{{key}}}", str(val))
        return rendered


class _SafeDict(dict):
    """Return the placeholder string itself for missing keys."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


# ---------------------------------------------------------------------------
# 1. schedule_appointment_reminders
# ---------------------------------------------------------------------------

async def schedule_appointment_reminders(
    db: AsyncSession,
    practice_id: UUID,
    appointment_id: UUID,
) -> list[dict]:
    """Schedule the full set of enhanced reminders when an appointment is booked.

    Creates up to three reminder records:
      - **confirmation** : sent immediately (scheduled_for = now)
      - **24h**          : 24 hours before the appointment
      - **2h**           : 2 hours before the appointment

    Each record stores a pre-rendered, bilingual SMS body so the background
    send loop never needs to re-query patient/practice data.

    Returns a list of dicts describing the created reminders, e.g.::

        [{"id": "...", "stage": "confirmation", "scheduled_for": "..."}]
    """
    # Fetch appointment with patient + practice eagerly
    stmt = (
        select(Appointment)
        .options(
            joinedload(Appointment.patient),
            joinedload(Appointment.practice),
        )
        .where(
            and_(
                Appointment.id == appointment_id,
                Appointment.practice_id == practice_id,
            )
        )
    )
    result = await db.execute(stmt)
    appointment = result.unique().scalar_one_or_none()

    if not appointment:
        logger.error(
            "schedule_appointment_reminders: appointment %s not found for practice %s",
            appointment_id, practice_id,
        )
        return []

    patient: Patient | None = appointment.patient
    practice: Practice | None = appointment.practice

    if not patient:
        logger.warning(
            "schedule_appointment_reminders: no patient for appointment %s",
            appointment_id,
        )
        return []

    if not patient.phone:
        logger.info(
            "schedule_appointment_reminders: patient %s has no phone, skipping",
            patient.id,
        )
        return []

    # Resolve timezone
    timezone_str = practice.timezone if practice else "America/New_York"
    try:
        tz = ZoneInfo(timezone_str)
    except (KeyError, Exception):
        tz = ZoneInfo("America/New_York")

    # Build appointment datetime in practice timezone
    appt_dt = datetime.combine(appointment.date, appointment.time, tzinfo=tz)
    now = datetime.now(timezone.utc)

    # Language
    language = patient.language_preference or "en"

    # Format display strings
    formatted_date, formatted_time = format_appointment_datetime(
        appointment.date,
        appointment.time,
        timezone_str,
        language,
    )

    practice_name = practice.name if practice else "our office"
    practice_phone = practice.phone if practice else ""

    template_vars = {
        "practice_name": practice_name,
        "date": formatted_date,
        "time": formatted_time,
        "phone": practice_phone,
    }

    # Define stages: (stage_key, offset_before_appt | None for "now")
    stages = [
        ("confirmation", None),         # send now
        ("24h", timedelta(hours=24)),    # 24 h before
        ("2h", timedelta(hours=2)),      # 2 h before
    ]

    created: list[dict] = []

    for stage_key, offset in stages:
        if offset is None:
            scheduled_for = now
        else:
            scheduled_for = appt_dt - offset

        # Skip if reminder time is already in the past (except confirmation
        # which is always "now")
        if offset is not None and scheduled_for <= now:
            logger.info(
                "schedule_appointment_reminders: %s reminder for %s is in the past, skipping",
                stage_key, appointment_id,
            )
            continue

        # Duplicate guard — same appointment + same scheduled_for (unique DB index)
        dup_stmt = select(AppointmentReminder.id).where(
            and_(
                AppointmentReminder.appointment_id == appointment_id,
                AppointmentReminder.scheduled_for == scheduled_for,
                AppointmentReminder.status.in_(["pending", "sent"]),
            )
        )
        dup = (await db.execute(dup_stmt)).scalar_one_or_none()
        if dup:
            logger.info(
                "schedule_appointment_reminders: %s reminder already exists for %s",
                stage_key, appointment_id,
            )
            continue

        message_content = _render_template(stage_key, language, template_vars)

        reminder = AppointmentReminder(
            practice_id=practice_id,
            appointment_id=appointment_id,
            patient_id=patient.id,
            reminder_type="sms",
            scheduled_for=scheduled_for,
            status="pending",
            message_content=message_content,
        )
        db.add(reminder)
        created.append({
            "stage": stage_key,
            "scheduled_for": scheduled_for.isoformat(),
        })

    if created:
        await db.flush()
        # Backfill IDs after flush assigns server defaults
        logger.info(
            "schedule_appointment_reminders: scheduled %d reminders for appointment %s",
            len(created), appointment_id,
        )

    return created


# ---------------------------------------------------------------------------
# 2. process_pending_reminders
# ---------------------------------------------------------------------------

async def process_pending_reminders(db: AsyncSession) -> dict:
    """Process all pending reminders whose scheduled_for time has arrived.

    Called every 60 seconds by the background ``_reminder_check_loop`` in
    ``main.py``.  For each due reminder:

    1. Verify the parent appointment is still active (skip cancelled / no-show).
    2. Send SMS via Twilio using practice-scoped credentials.
    3. Update status to ``sent`` or ``failed``.

    Returns::

        {"sent": int, "failed": int, "skipped": int}
    """
    now = datetime.now(timezone.utc)
    sent = 0
    failed = 0
    skipped = 0

    try:
        stmt = (
            select(AppointmentReminder)
            .options(
                joinedload(AppointmentReminder.patient),
                joinedload(AppointmentReminder.appointment),
            )
            .where(
                and_(
                    AppointmentReminder.status == "pending",
                    AppointmentReminder.scheduled_for <= now,
                    AppointmentReminder.attempts < MAX_SEND_ATTEMPTS,
                )
            )
            .order_by(AppointmentReminder.scheduled_for)
            .limit(100)
        )
        result = await db.execute(stmt)
        reminders = result.unique().scalars().all()

        if not reminders:
            return {"sent": 0, "failed": 0, "skipped": 0}

        logger.info(
            "process_pending_reminders: found %d due reminders", len(reminders),
        )

        for reminder in reminders:
            try:
                # Skip if appointment was cancelled or already marked no-show
                appointment: Appointment | None = reminder.appointment
                if appointment and appointment.status in ("cancelled", "no_show"):
                    reminder.status = "cancelled"
                    await db.commit()
                    skipped += 1
                    continue

                # Exponential backoff on retries
                if reminder.attempts > 0 and reminder.updated_at:
                    backoff_minutes = 2 ** reminder.attempts
                    retry_after = reminder.updated_at + timedelta(minutes=backoff_minutes)
                    if now < retry_after:
                        skipped += 1
                        continue

                patient: Patient | None = reminder.patient
                if not patient or not patient.phone:
                    reminder.status = "failed"
                    reminder.attempts += 1
                    await db.commit()
                    failed += 1
                    continue

                # Get Twilio credentials for the practice
                try:
                    account_sid, auth_token, from_phone = await get_twilio_credentials(
                        db, reminder.practice_id,
                    )
                except ValueError as cred_err:
                    logger.error(
                        "process_pending_reminders: Twilio credentials error for practice %s: %s",
                        reminder.practice_id, cred_err,
                    )
                    reminder.status = "failed"
                    reminder.attempts += 1
                    await db.commit()
                    failed += 1
                    continue

                sms_result = await send_sms(
                    to_number=patient.phone,
                    from_number=from_phone,
                    body=reminder.message_content or "",
                    account_sid=account_sid,
                    auth_token=auth_token,
                )

                reminder.attempts += 1

                if sms_result["success"]:
                    reminder.status = "sent"
                    reminder.sent_at = datetime.now(timezone.utc)
                    reminder.message_sid = sms_result.get("message_sid")
                    sent += 1
                else:
                    if reminder.attempts >= MAX_SEND_ATTEMPTS:
                        reminder.status = "failed"
                    failed += 1

                # Commit each individually so a single failure doesn't roll back
                # the entire batch and cause duplicate SMS sends.
                await db.commit()

            except Exception as rem_err:
                await db.rollback()
                logger.warning(
                    "process_pending_reminders: error on reminder %s: %s",
                    reminder.id, rem_err,
                )
                failed += 1

    except Exception as e:
        logger.exception(
            "process_pending_reminders: batch error: %s", e,
        )

    logger.info(
        "process_pending_reminders: sent=%d failed=%d skipped=%d",
        sent, failed, skipped,
    )
    return {"sent": sent, "failed": failed, "skipped": skipped}


# ---------------------------------------------------------------------------
# 3. process_no_show_followups
# ---------------------------------------------------------------------------

async def process_no_show_followups(db: AsyncSession) -> dict:
    """Send a follow-up SMS to patients who missed their appointment.

    Finds appointments where:
    - ``status = 'no_show'``
    - The appointment date/time is at least 30 minutes in the past
    - No follow-up reminder has been sent yet for that appointment

    For each match, renders a bilingual no-show template and creates + sends
    a new ``AppointmentReminder`` record.

    Returns::

        {"sent": int, "failed": int}
    """
    now = datetime.now(timezone.utc)
    sent = 0
    failed = 0

    try:
        # Subquery: appointment IDs that already have a no-show follow-up
        already_followed_up = (
            select(AppointmentReminder.appointment_id)
            .where(
                and_(
                    AppointmentReminder.message_content.ilike("%missed you%"),
                    AppointmentReminder.status.in_(["sent", "pending"]),
                )
            )
        ).subquery()

        stmt = (
            select(Appointment)
            .options(
                joinedload(Appointment.patient),
                joinedload(Appointment.practice),
            )
            .where(
                and_(
                    Appointment.status == "no_show",
                    Appointment.id.notin_(select(already_followed_up.c.appointment_id)),
                )
            )
            .limit(50)
        )
        result = await db.execute(stmt)
        appointments = result.unique().scalars().all()

        if not appointments:
            return {"sent": 0, "failed": 0}

        logger.info(
            "process_no_show_followups: found %d no-show appointments to follow up",
            len(appointments),
        )

        for appointment in appointments:
            try:
                patient: Patient | None = appointment.patient
                practice: Practice | None = appointment.practice

                if not patient or not patient.phone:
                    continue

                # Verify the appointment time + 30 min has passed
                timezone_str = practice.timezone if practice else "America/New_York"
                try:
                    tz = ZoneInfo(timezone_str)
                except (KeyError, Exception):
                    tz = ZoneInfo("America/New_York")

                appt_dt = datetime.combine(
                    appointment.date, appointment.time, tzinfo=tz,
                )
                if now < appt_dt + timedelta(minutes=30):
                    continue  # too early for follow-up

                language = patient.language_preference or "en"
                practice_name = practice.name if practice else "our office"
                practice_phone = practice.phone if practice else ""

                message = _render_template("no_show", language, {
                    "practice_name": practice_name,
                    "phone": practice_phone,
                })

                # Create reminder record
                reminder = AppointmentReminder(
                    practice_id=appointment.practice_id,
                    appointment_id=appointment.id,
                    patient_id=appointment.patient_id,
                    reminder_type="sms",
                    scheduled_for=now,
                    status="pending",
                    message_content=message,
                )
                db.add(reminder)
                await db.flush()

                # Send immediately
                try:
                    account_sid, auth_token, from_phone = await get_twilio_credentials(
                        db, appointment.practice_id,
                    )
                except ValueError as cred_err:
                    logger.error(
                        "process_no_show_followups: Twilio creds error practice %s: %s",
                        appointment.practice_id, cred_err,
                    )
                    reminder.status = "failed"
                    reminder.attempts = 1
                    await db.commit()
                    failed += 1
                    continue

                sms_result = await send_sms(
                    to_number=patient.phone,
                    from_number=from_phone,
                    body=message,
                    account_sid=account_sid,
                    auth_token=auth_token,
                )

                reminder.attempts = 1
                if sms_result["success"]:
                    reminder.status = "sent"
                    reminder.sent_at = datetime.now(timezone.utc)
                    reminder.message_sid = sms_result.get("message_sid")
                    sent += 1
                else:
                    reminder.status = "failed"
                    failed += 1

                await db.commit()

            except Exception as appt_err:
                await db.rollback()
                logger.warning(
                    "process_no_show_followups: error for appointment %s: %s",
                    appointment.id, appt_err,
                )
                failed += 1

    except Exception as e:
        logger.exception(
            "process_no_show_followups: batch error: %s", e,
        )

    logger.info(
        "process_no_show_followups: sent=%d failed=%d", sent, failed,
    )
    return {"sent": sent, "failed": failed}


# ---------------------------------------------------------------------------
# 4. handle_reminder_response
# ---------------------------------------------------------------------------

async def handle_reminder_response(
    db: AsyncSession,
    phone: str,
    response_text: str,
) -> dict:
    """Process an inbound SMS reply from a patient.

    Matches the reply to the most recently *sent* reminder for the phone
    number and interprets the keyword:

    - **CONFIRM / YES / SI / CONFIRMAR** -- mark appointment as ``confirmed``
    - **CANCEL / NO / CANCELAR**         -- mark appointment as ``cancelled``,
      cancel remaining pending reminders, and trigger waitlist check
    - **RESCHEDULE / REPROGRAMAR**       -- flag for manual staff follow-up

    Returns::

        {
            "action_taken": "confirmed" | "cancelled" | "reschedule_requested"
                            | "unknown" | "no_match",
            "appointment_id": str | None,
            "reply_message": str,
        }
    """
    normalized = response_text.strip().upper()

    # Find the most recent sent reminder for this phone number
    stmt = (
        select(AppointmentReminder)
        .join(Patient, AppointmentReminder.patient_id == Patient.id)
        .options(joinedload(AppointmentReminder.appointment))
        .where(
            and_(
                Patient.phone == phone,
                AppointmentReminder.status == "sent",
            )
        )
        .order_by(AppointmentReminder.sent_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    reminder = result.unique().scalar_one_or_none()

    if not reminder:
        logger.info(
            "handle_reminder_response: no sent reminder for phone %s", phone,
        )
        return {
            "action_taken": "no_match",
            "appointment_id": None,
            "reply_message": (
                "We could not find an active reminder for your number. "
                "Please call our office for assistance."
            ),
        }

    # Store the raw response on the reminder
    reminder.response = response_text.strip()
    appointment: Appointment | None = reminder.appointment

    # --- CONFIRM ---
    if normalized in ("CONFIRM", "CONFIRMAR", "YES", "SI", "Y"):
        if appointment and appointment.status in ("booked", "confirmed"):
            appointment.status = "confirmed"
        await db.flush()
        await db.commit()

        logger.info(
            "handle_reminder_response: confirmed appointment %s",
            reminder.appointment_id,
        )
        return {
            "action_taken": "confirmed",
            "appointment_id": str(reminder.appointment_id),
            "reply_message": (
                "Thank you! Your appointment has been confirmed. "
                "We look forward to seeing you."
            ),
        }

    # --- CANCEL ---
    if normalized in ("CANCEL", "CANCELAR", "NO"):
        if appointment and appointment.status not in ("cancelled",):
            appointment.status = "cancelled"
            appointment.notes = (
                (appointment.notes or "")
                + "\nCancelled by patient via SMS reply."
            ).strip()

        # Cancel remaining pending reminders for this appointment
        cancel_stmt = (
            update(AppointmentReminder)
            .where(
                and_(
                    AppointmentReminder.appointment_id == reminder.appointment_id,
                    AppointmentReminder.status == "pending",
                )
            )
            .values(status="cancelled")
        )
        await db.execute(cancel_stmt)

        await db.flush()
        await db.commit()

        # Trigger waitlist check (best-effort, do not block response)
        if appointment:
            try:
                from app.services.waitlist_service import check_waitlist_on_cancellation
                await check_waitlist_on_cancellation(
                    db, appointment.practice_id, appointment,
                )
            except Exception as wl_err:
                logger.warning(
                    "handle_reminder_response: waitlist check failed: %s", wl_err,
                )

        logger.info(
            "handle_reminder_response: cancelled appointment %s",
            reminder.appointment_id,
        )
        return {
            "action_taken": "cancelled",
            "appointment_id": str(reminder.appointment_id),
            "reply_message": (
                "Your appointment has been cancelled. "
                "Please call our office if you would like to reschedule."
            ),
        }

    # --- RESCHEDULE ---
    if normalized in ("RESCHEDULE", "REPROGRAMAR"):
        if appointment:
            appointment.notes = (
                (appointment.notes or "")
                + "\nPatient requested reschedule via SMS reply."
            ).strip()
        await db.flush()
        await db.commit()

        logger.info(
            "handle_reminder_response: reschedule requested for appointment %s",
            reminder.appointment_id,
        )
        return {
            "action_taken": "reschedule_requested",
            "appointment_id": str(reminder.appointment_id),
            "reply_message": (
                "We have received your request to reschedule. "
                "A member of our team will call you to arrange a new time."
            ),
        }

    # --- UNKNOWN ---
    await db.flush()
    await db.commit()

    logger.info(
        "handle_reminder_response: unrecognized reply '%s' from %s",
        response_text.strip()[:50], phone,
    )
    return {
        "action_taken": "unknown",
        "appointment_id": str(reminder.appointment_id),
        "reply_message": (
            "Thank you for your reply. "
            "Please reply CONFIRM, CANCEL, or RESCHEDULE. "
            "Or call our office for assistance."
        ),
    }


# ---------------------------------------------------------------------------
# 5. get_reminder_stats
# ---------------------------------------------------------------------------

async def get_reminder_stats(
    db: AsyncSession,
    practice_id: UUID,
) -> dict:
    """Return aggregate reminder statistics for a practice.

    Returns::

        {
            "total": int,
            "pending": int,
            "sent": int,
            "failed": int,
            "cancelled": int,
            "confirmed_by_patient": int,
            "cancelled_by_patient": int,
            "delivery_rate": float,       # sent / (sent + failed) * 100
            "confirmation_rate": float,   # confirmed / sent * 100
        }
    """
    # Count by status
    status_stmt = (
        select(AppointmentReminder.status, func.count(AppointmentReminder.id))
        .where(AppointmentReminder.practice_id == practice_id)
        .group_by(AppointmentReminder.status)
    )
    status_result = await db.execute(status_stmt)
    counts = {row[0]: row[1] for row in status_result.all()}

    total = sum(counts.values())
    pending = counts.get("pending", 0)
    sent = counts.get("sent", 0)
    failed_count = counts.get("failed", 0)
    cancelled = counts.get("cancelled", 0)

    # Count patient confirmations (reminders with a response containing CONFIRM-like words)
    confirmed_stmt = (
        select(func.count(AppointmentReminder.id))
        .where(
            and_(
                AppointmentReminder.practice_id == practice_id,
                AppointmentReminder.response.isnot(None),
                func.upper(AppointmentReminder.response).in_([
                    "CONFIRM", "CONFIRMAR", "YES", "SI", "Y",
                ]),
            )
        )
    )
    confirmed_by_patient = (await db.execute(confirmed_stmt)).scalar_one()

    # Count patient cancellations
    cancelled_stmt = (
        select(func.count(AppointmentReminder.id))
        .where(
            and_(
                AppointmentReminder.practice_id == practice_id,
                AppointmentReminder.response.isnot(None),
                func.upper(AppointmentReminder.response).in_([
                    "CANCEL", "CANCELAR", "NO",
                ]),
            )
        )
    )
    cancelled_by_patient = (await db.execute(cancelled_stmt)).scalar_one()

    # Rates
    delivery_denominator = sent + failed_count
    delivery_rate = round(
        (sent / delivery_denominator) * 100, 1,
    ) if delivery_denominator > 0 else 0.0

    confirmation_rate = round(
        (confirmed_by_patient / sent) * 100, 1,
    ) if sent > 0 else 0.0

    return {
        "total": total,
        "pending": pending,
        "sent": sent,
        "failed": failed_count,
        "cancelled": cancelled,
        "confirmed_by_patient": confirmed_by_patient,
        "cancelled_by_patient": cancelled_by_patient,
        "delivery_rate": delivery_rate,
        "confirmation_rate": confirmation_rate,
    }


# ---------------------------------------------------------------------------
# 6. get_reminders_for_appointment
# ---------------------------------------------------------------------------

async def get_reminders_for_appointment(
    db: AsyncSession,
    appointment_id: UUID,
    practice_id: UUID,
) -> list[AppointmentReminder]:
    """Return all reminder records for a given appointment, newest first."""
    stmt = (
        select(AppointmentReminder)
        .options(joinedload(AppointmentReminder.patient))
        .where(
            and_(
                AppointmentReminder.appointment_id == appointment_id,
                AppointmentReminder.practice_id == practice_id,
            )
        )
        .order_by(AppointmentReminder.scheduled_for.desc())
    )
    result = await db.execute(stmt)
    return list(result.unique().scalars().all())
