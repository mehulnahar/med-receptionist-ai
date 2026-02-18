"""
Reminder service for the outbound appointment reminder system.

Handles scheduling, sending, cancelling, and processing of SMS appointment
reminders. Uses the existing sms_service for Twilio delivery and follows
the same practice-scoped, async patterns as the rest of the codebase.
"""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

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

# Maximum number of send attempts before marking as failed
MAX_SEND_ATTEMPTS = 3

# ---------------------------------------------------------------------------
# Reminder message templates
# ---------------------------------------------------------------------------

REMINDER_TEMPLATES = {
    "en": (
        "Hi {patient_name}, this is a reminder of your appointment at "
        "Dr. Stefanides' office on {date} at {time}. "
        "Reply CONFIRM to confirm, CANCEL to cancel, or RESCHEDULE to reschedule."
    ),
    "es": (
        "Hola {patient_name}, este es un recordatorio de su cita en la "
        "oficina del Dr. Stefanides el {date} a las {time}. "
        "Responda CONFIRMAR para confirmar, CANCELAR para cancelar, "
        "o REPROGRAMAR para reprogramar."
    ),
}


# ---------------------------------------------------------------------------
# 1. schedule_reminders
# ---------------------------------------------------------------------------

async def schedule_reminders(
    db: AsyncSession,
    appointment: Appointment,
) -> list[AppointmentReminder]:
    """
    Auto-schedule reminders when an appointment is booked.

    Creates two SMS reminders:
      - 24 hours before the appointment
      - 2 hours before the appointment

    Skips scheduling if the appointment time is already past or if the
    reminder time would be in the past.

    Returns the list of created AppointmentReminder objects.
    """
    created_reminders: list[AppointmentReminder] = []

    try:
        # Load patient for name and language
        patient: Patient = appointment.patient
        practice: Practice = appointment.practice

        if not patient:
            logger.warning(
                "schedule_reminders: no patient for appointment %s, skipping",
                appointment.id,
            )
            return []

        if not patient.phone:
            logger.info(
                "schedule_reminders: patient %s has no phone, skipping reminders",
                patient.id,
            )
            return []

        # Build the appointment datetime (naive date+time from DB, practice timezone)
        timezone_str = practice.timezone or "America/New_York"
        from zoneinfo import ZoneInfo

        try:
            tz = ZoneInfo(timezone_str)
        except (KeyError, Exception):
            tz = ZoneInfo("America/New_York")

        appt_dt = datetime.combine(appointment.date, appointment.time, tzinfo=tz)
        now = datetime.now(timezone.utc)

        # Determine language
        language = patient.language_preference or "en"

        # Format date/time for the message
        formatted_date, formatted_time = format_appointment_datetime(
            appointment.date,
            appointment.time,
            timezone_str,
            language,
        )

        patient_name = f"{patient.first_name} {patient.last_name}"

        # Select template
        template = REMINDER_TEMPLATES.get(language) or REMINDER_TEMPLATES["en"]
        message_content = template.format(
            patient_name=patient_name,
            date=formatted_date,
            time=formatted_time,
        )

        # Define reminder offsets: (hours_before, label)
        offsets = [
            (timedelta(hours=24), "24h"),
            (timedelta(hours=2), "2h"),
        ]

        for offset, label in offsets:
            reminder_time = appt_dt - offset

            # Skip if the reminder time is already in the past
            if reminder_time <= now:
                logger.info(
                    "schedule_reminders: %s reminder for appointment %s is in the past, skipping",
                    label, appointment.id,
                )
                continue

            # Check for duplicate (same appointment, same scheduled_for)
            existing_stmt = select(AppointmentReminder).where(
                and_(
                    AppointmentReminder.appointment_id == appointment.id,
                    AppointmentReminder.scheduled_for == reminder_time,
                    AppointmentReminder.status.in_(["pending", "sent"]),
                )
            )
            existing_result = await db.execute(existing_stmt)
            if existing_result.scalar_one_or_none():
                logger.info(
                    "schedule_reminders: %s reminder already exists for appointment %s, skipping",
                    label, appointment.id,
                )
                continue

            reminder = AppointmentReminder(
                practice_id=appointment.practice_id,
                appointment_id=appointment.id,
                patient_id=appointment.patient_id,
                reminder_type="sms",
                scheduled_for=reminder_time,
                status="pending",
                message_content=message_content,
            )
            db.add(reminder)
            created_reminders.append(reminder)

        if created_reminders:
            await db.flush()
            logger.info(
                "schedule_reminders: scheduled %d reminders for appointment %s",
                len(created_reminders), appointment.id,
            )

    except Exception as e:
        logger.exception(
            "schedule_reminders: error scheduling reminders for appointment %s: %s",
            appointment.id, e,
        )

    return created_reminders


# ---------------------------------------------------------------------------
# 2. send_sms_reminder
# ---------------------------------------------------------------------------

async def send_sms_reminder(
    db: AsyncSession,
    reminder: AppointmentReminder,
) -> bool:
    """
    Send a single SMS reminder via Twilio.

    Updates the reminder status, sent_at, message_sid, and attempts count.
    Returns True if sent successfully, False otherwise.
    """
    try:
        # Load patient for phone number
        patient: Patient = reminder.patient

        if not patient or not patient.phone:
            logger.warning(
                "send_sms_reminder: no phone for reminder %s, marking failed",
                reminder.id,
            )
            reminder.status = "failed"
            reminder.attempts += 1
            await db.flush()
            return False

        # Get Twilio credentials for this practice
        try:
            account_sid, auth_token, from_phone = await get_twilio_credentials(
                db, reminder.practice_id,
            )
        except ValueError as e:
            logger.error(
                "send_sms_reminder: Twilio credentials error for practice %s: %s",
                reminder.practice_id, e,
            )
            reminder.status = "failed"
            reminder.attempts += 1
            await db.flush()
            return False

        # Send the SMS
        result = await send_sms(
            to_number=patient.phone,
            from_number=from_phone,
            body=reminder.message_content or "",
            account_sid=account_sid,
            auth_token=auth_token,
        )

        reminder.attempts += 1

        if result["success"]:
            reminder.status = "sent"
            reminder.sent_at = datetime.now(timezone.utc)
            reminder.message_sid = result.get("message_sid")
            logger.info(
                "send_sms_reminder: sent reminder %s to %s (SID: %s)",
                reminder.id, patient.phone, result.get("message_sid"),
            )
            await db.flush()
            return True
        else:
            # Mark as failed only after MAX_SEND_ATTEMPTS
            if reminder.attempts >= MAX_SEND_ATTEMPTS:
                reminder.status = "failed"
            logger.error(
                "send_sms_reminder: failed to send reminder %s (attempt %d): %s",
                reminder.id, reminder.attempts, result.get("error"),
            )
            await db.flush()
            return False

    except Exception as e:
        logger.exception(
            "send_sms_reminder: unexpected error for reminder %s: %s",
            reminder.id, e,
        )
        reminder.attempts += 1
        if reminder.attempts >= MAX_SEND_ATTEMPTS:
            reminder.status = "failed"
        await db.flush()
        return False


# ---------------------------------------------------------------------------
# 3. process_pending_reminders
# ---------------------------------------------------------------------------

async def process_pending_reminders(db: AsyncSession) -> int:
    """
    Find and send all due reminders.

    Selects all pending reminders whose scheduled_for time has passed and
    that have not exceeded the maximum send attempts. Sends each via SMS.

    Returns the number of reminders successfully sent.
    """
    now = datetime.now(timezone.utc)
    sent_count = 0

    try:
        stmt = (
            select(AppointmentReminder)
            .where(
                and_(
                    AppointmentReminder.status == "pending",
                    AppointmentReminder.scheduled_for <= now,
                    AppointmentReminder.attempts < MAX_SEND_ATTEMPTS,
                )
            )
            .order_by(AppointmentReminder.scheduled_for)
            .limit(100)  # Process in batches to avoid long-running transactions
        )
        result = await db.execute(stmt)
        reminders = result.scalars().all()

        if not reminders:
            return 0

        logger.info(
            "process_pending_reminders: found %d due reminders to process",
            len(reminders),
        )

        for reminder in reminders:
            # Double-check the appointment is still active
            appointment: Appointment = reminder.appointment
            if appointment and appointment.status in ("cancelled", "no_show"):
                reminder.status = "cancelled"
                await db.flush()
                logger.info(
                    "process_pending_reminders: cancelled reminder %s (appointment %s is %s)",
                    reminder.id, appointment.id, appointment.status,
                )
                continue

            success = await send_sms_reminder(db, reminder)
            if success:
                sent_count += 1

        logger.info(
            "process_pending_reminders: sent %d out of %d reminders",
            sent_count, len(reminders),
        )

    except Exception as e:
        logger.exception(
            "process_pending_reminders: error processing reminders: %s", e,
        )

    return sent_count


# ---------------------------------------------------------------------------
# 4. cancel_reminders
# ---------------------------------------------------------------------------

async def cancel_reminders(
    db: AsyncSession,
    appointment_id: UUID,
) -> int:
    """
    Cancel all pending reminders for a given appointment.

    Called when an appointment is cancelled or rescheduled.
    Returns the number of reminders cancelled.
    """
    try:
        stmt = (
            update(AppointmentReminder)
            .where(
                and_(
                    AppointmentReminder.appointment_id == appointment_id,
                    AppointmentReminder.status == "pending",
                )
            )
            .values(status="cancelled")
        )
        result = await db.execute(stmt)
        cancelled_count = result.rowcount

        if cancelled_count > 0:
            logger.info(
                "cancel_reminders: cancelled %d reminders for appointment %s",
                cancelled_count, appointment_id,
            )

        return cancelled_count

    except Exception as e:
        logger.exception(
            "cancel_reminders: error cancelling reminders for appointment %s: %s",
            appointment_id, e,
        )
        return 0


# ---------------------------------------------------------------------------
# 5. handle_sms_reply
# ---------------------------------------------------------------------------

async def handle_sms_reply(
    db: AsyncSession,
    from_number: str,
    body: str,
) -> dict:
    """
    Handle an incoming SMS reply from a patient.

    Matches the reply to the most recent sent reminder for that phone number
    and processes CONFIRM, CANCEL, or RESCHEDULE keywords.

    Returns a result dict with action taken and reply message.
    """
    try:
        normalized_body = body.strip().upper()

        # Find the most recently sent reminder for this phone number
        stmt = (
            select(AppointmentReminder)
            .join(Patient, AppointmentReminder.patient_id == Patient.id)
            .where(
                and_(
                    Patient.phone == from_number,
                    AppointmentReminder.status == "sent",
                )
            )
            .order_by(AppointmentReminder.sent_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        reminder = result.scalar_one_or_none()

        if not reminder:
            logger.info(
                "handle_sms_reply: no recent reminder found for phone %s",
                from_number,
            )
            return {
                "action": "none",
                "message": "No recent reminder found for this number",
            }

        # Store the patient's response
        reminder.response = body.strip()
        appointment: Appointment = reminder.appointment

        if normalized_body in ("CONFIRM", "CONFIRMAR", "YES", "SI", "Y"):
            # Confirm the appointment
            if appointment and appointment.status in ("booked", "confirmed"):
                appointment.status = "confirmed"
            await db.flush()

            logger.info(
                "handle_sms_reply: patient confirmed appointment %s via SMS",
                reminder.appointment_id,
            )
            return {
                "action": "confirmed",
                "appointment_id": str(reminder.appointment_id),
                "reply_message": (
                    "Thank you! Your appointment has been confirmed. "
                    "We look forward to seeing you."
                ),
            }

        elif normalized_body in ("CANCEL", "CANCELAR", "NO"):
            # Cancel the appointment
            if appointment and appointment.status not in ("cancelled",):
                appointment.status = "cancelled"
                appointment.notes = (
                    (appointment.notes or "") + "\nCancelled by patient via SMS reply."
                ).strip()
            # Cancel remaining pending reminders for this appointment
            await cancel_reminders(db, reminder.appointment_id)
            await db.flush()

            logger.info(
                "handle_sms_reply: patient cancelled appointment %s via SMS",
                reminder.appointment_id,
            )
            return {
                "action": "cancelled",
                "appointment_id": str(reminder.appointment_id),
                "reply_message": (
                    "Your appointment has been cancelled. "
                    "Please call our office if you'd like to reschedule."
                ),
            }

        elif normalized_body in ("RESCHEDULE", "REPROGRAMAR"):
            # Flag for manual reschedule (can't do interactively via SMS)
            if appointment:
                appointment.notes = (
                    (appointment.notes or "") + "\nPatient requested reschedule via SMS reply."
                ).strip()
            await db.flush()

            logger.info(
                "handle_sms_reply: patient requested reschedule for appointment %s via SMS",
                reminder.appointment_id,
            )
            return {
                "action": "reschedule_requested",
                "appointment_id": str(reminder.appointment_id),
                "reply_message": (
                    "We've received your request to reschedule. "
                    "A member of our team will call you to arrange a new time."
                ),
            }

        else:
            # Unknown reply -- store it and acknowledge
            await db.flush()
            logger.info(
                "handle_sms_reply: unrecognized reply '%s' from %s for appointment %s",
                body.strip(), from_number, reminder.appointment_id,
            )
            return {
                "action": "unknown",
                "appointment_id": str(reminder.appointment_id),
                "reply_message": (
                    "Thank you for your reply. "
                    "Please reply CONFIRM, CANCEL, or RESCHEDULE. "
                    "Or call our office for assistance."
                ),
            }

    except Exception as e:
        logger.exception(
            "handle_sms_reply: error processing reply from %s: %s",
            from_number, e,
        )
        return {
            "action": "error",
            "message": f"Error processing reply: {str(e)}",
        }
