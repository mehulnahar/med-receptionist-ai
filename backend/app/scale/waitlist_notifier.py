"""
Intelligent waitlist auto-notification service.

When an appointment is cancelled, automatically notifies the highest-priority
waitlisted patients whose preferences match the freed slot. Handles responses,
expiry, and cascading to the next person in line.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

logger = logging.getLogger(__name__)


async def on_appointment_cancelled(
    db: AsyncSession, appointment_id: str
) -> list[dict]:
    """Called when an appointment is cancelled — notifies matching waitlist patients.

    Returns list of notified entries.
    """
    # Fetch the cancelled appointment details
    result = await db.execute(
        text("""
            SELECT a.id, a.practice_id, a.date, a.start_time, a.end_time,
                   a.appointment_type_id, a.provider_id,
                   u.first_name AS provider_first, u.last_name AS provider_last
            FROM appointments a
            LEFT JOIN users u ON a.provider_id = u.id
            WHERE a.id = :aid
        """),
        {"aid": appointment_id},
    )
    appt = result.fetchone()
    if not appt:
        logger.warning("Cancelled appointment %s not found", appointment_id)
        return []

    # Find matching waitlist entries (top 3 by priority, then created_at)
    query = """
        SELECT id, patient_name, patient_phone, appointment_type_id,
               preferred_date_start, preferred_date_end,
               preferred_time_start, preferred_time_end
        FROM waitlist_entries
        WHERE practice_id = :pid
          AND status = 'waiting'
          AND (appointment_type_id IS NULL OR appointment_type_id = :atid)
          AND (preferred_date_start IS NULL OR preferred_date_start <= :appt_date)
          AND (preferred_date_end IS NULL OR preferred_date_end >= :appt_date)
          AND (preferred_time_start IS NULL OR preferred_time_start <= :appt_time)
          AND (preferred_time_end IS NULL OR preferred_time_end >= :appt_time)
        ORDER BY priority ASC, created_at ASC
        LIMIT 3
    """
    matches = await db.execute(
        text(query),
        {
            "pid": str(appt.practice_id),
            "atid": str(appt.appointment_type_id) if appt.appointment_type_id else None,
            "appt_date": appt.date,
            "appt_time": appt.start_time,
        },
    )
    entries = matches.fetchall()

    if not entries:
        logger.info("No matching waitlist entries for cancelled appointment %s", appointment_id)
        return []

    provider_name = f"{appt.provider_first or ''} {appt.provider_last or ''}".strip()
    appt_date_str = appt.date.strftime("%B %d") if appt.date else "soon"
    appt_time_str = appt.start_time.strftime("%-I:%M %p") if appt.start_time else ""

    notified = []
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

    for entry in entries:
        # Build bilingual message
        msg_en = (
            f"Great news! A {appt_time_str} appointment on {appt_date_str} "
            f"with Dr. {provider_name} just opened up. "
            f"Reply YES within 30 min to book it, or it goes to the next person."
        )
        msg_es = (
            f"Buenas noticias! Una cita a las {appt_time_str} el {appt_date_str} "
            f"con Dr. {provider_name} acaba de abrirse. "
            f"Responda SI en 30 min para reservarla."
        )
        full_message = f"{msg_en}\n---\n{msg_es}"

        sms_sent = await _send_waitlist_sms(
            entry.patient_phone, full_message, str(appt.practice_id)
        )

        # Update entry status
        await db.execute(
            text("""
                UPDATE waitlist_entries
                SET status = 'notified',
                    notified_at = NOW(),
                    expires_at = :expires_at,
                    updated_at = NOW()
                WHERE id = :eid
            """),
            {"eid": str(entry.id), "expires_at": expires_at},
        )

        notified.append({
            "entry_id": str(entry.id),
            "patient_name": entry.patient_name,
            "patient_phone": entry.patient_phone,
            "sms_sent": sms_sent,
        })

    await db.commit()
    logger.info(
        "Notified %d waitlist patients for cancelled appointment %s",
        len(notified),
        appointment_id,
    )
    return notified


async def process_waitlist_response(
    db: AsyncSession, phone_number: str, response_text: str
) -> dict:
    """Process a patient's reply to a waitlist notification.

    YES/SI → book the appointment
    NO/anything else → reset to waiting, notify next person
    """
    response_upper = response_text.strip().upper()
    is_yes = response_upper in ("YES", "SI", "SÍ", "Y", "S")

    # Find most recent 'notified' entry for this phone that hasn't expired
    result = await db.execute(
        text("""
            SELECT id, practice_id, patient_name, patient_phone,
                   appointment_type_id, notified_at
            FROM waitlist_entries
            WHERE patient_phone = :phone
              AND status = 'notified'
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY notified_at DESC
            LIMIT 1
        """),
        {"phone": phone_number},
    )
    entry = result.fetchone()

    if not entry:
        return {"status": "no_active_notification", "phone": phone_number}

    if is_yes:
        # Book the appointment
        await db.execute(
            text("""
                UPDATE waitlist_entries
                SET status = 'booked', updated_at = NOW()
                WHERE id = :eid
            """),
            {"eid": str(entry.id)},
        )

        # Send confirmation
        await _send_waitlist_sms(
            entry.patient_phone,
            "Your appointment has been booked! You'll receive a confirmation shortly.",
            str(entry.practice_id),
        )

        # Notify other notified entries for this practice that the slot was taken
        await db.execute(
            text("""
                UPDATE waitlist_entries
                SET status = 'waiting', notified_at = NULL, expires_at = NULL,
                    updated_at = NOW()
                WHERE practice_id = :pid
                  AND status = 'notified'
                  AND id != :eid
                  AND patient_phone != :phone
            """),
            {
                "pid": str(entry.practice_id),
                "eid": str(entry.id),
                "phone": phone_number,
            },
        )

        await db.commit()
        return {
            "status": "booked",
            "entry_id": str(entry.id),
            "patient_name": entry.patient_name,
        }
    else:
        # Reset to waiting
        await db.execute(
            text("""
                UPDATE waitlist_entries
                SET status = 'waiting', notified_at = NULL, expires_at = NULL,
                    updated_at = NOW()
                WHERE id = :eid
            """),
            {"eid": str(entry.id)},
        )
        await db.commit()

        return {
            "status": "declined",
            "entry_id": str(entry.id),
            "patient_name": entry.patient_name,
        }


async def expire_stale_notifications(db: AsyncSession) -> int:
    """Expire notifications past their 30-min window and reset to waiting."""
    result = await db.execute(
        text("""
            UPDATE waitlist_entries
            SET status = 'waiting', notified_at = NULL, expires_at = NULL,
                updated_at = NOW()
            WHERE status = 'notified'
              AND expires_at IS NOT NULL
              AND expires_at < NOW()
            RETURNING id, practice_id
        """)
    )
    expired = result.fetchall()
    if expired:
        await db.commit()
        logger.info("Expired %d stale waitlist notifications", len(expired))
    return len(expired)


# ---------------------------------------------------------------------------
# Background loop
# ---------------------------------------------------------------------------

async def waitlist_notification_loop() -> None:
    """Background task — expires stale notifications every 60 seconds."""
    from app.database import AsyncSessionLocal

    ADVISORY_LOCK_ID = 111222333
    logger.info("waitlist_notification_loop: started")

    while True:
        try:
            await asyncio.sleep(60)
            async with AsyncSessionLocal() as db:
                lock_result = await db.execute(
                    text(f"SELECT pg_try_advisory_lock({ADVISORY_LOCK_ID})")
                )
                acquired = lock_result.scalar_one()
                if not acquired:
                    continue

                try:
                    expired_count = await expire_stale_notifications(db)
                    if expired_count > 0:
                        logger.info(
                            "waitlist_notification_loop: expired %d entries",
                            expired_count,
                        )
                finally:
                    await db.execute(
                        text(f"SELECT pg_advisory_unlock({ADVISORY_LOCK_ID})")
                    )
                    await db.commit()

        except Exception as e:
            logger.warning("waitlist_notification_loop: error: %s", e)
            await asyncio.sleep(30)


# ---------------------------------------------------------------------------
# SMS helper
# ---------------------------------------------------------------------------

async def _send_waitlist_sms(
    phone: str, message: str, practice_id: str
) -> bool:
    """Send waitlist SMS via Twilio."""
    settings = get_settings()
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        logger.warning("Twilio not configured — waitlist SMS not sent")
        return False

    try:
        from twilio.rest import Client

        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.messages.create(
            body=message,
            from_=settings.TWILIO_ACCOUNT_SID,
            to=phone,
        )
        logger.info("Waitlist SMS sent to %s (practice=%s)", phone, practice_id)
        return True
    except Exception as e:
        logger.error("Failed to send waitlist SMS to %s: %s", phone, e)
        return False
