"""
Waitlist management service for the AI Medical Receptionist.

Handles adding patients to the waitlist, checking for matches when
appointments are cancelled, notifying patients via SMS, processing
YES/NO replies, and expiring stale entries.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.waitlist import WaitlistEntry
from app.models.appointment import Appointment
from app.models.appointment_type import AppointmentType
from app.models.practice import Practice
from app.services.sms_service import send_custom_sms

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Add to waitlist
# ---------------------------------------------------------------------------

async def add_to_waitlist(
    db: AsyncSession,
    practice_id: UUID,
    patient_name: str,
    patient_phone: str,
    patient_id: Optional[UUID] = None,
    appointment_type_id: Optional[UUID] = None,
    preferred_date_start=None,
    preferred_date_end=None,
    preferred_time_start=None,
    preferred_time_end=None,
    notes: Optional[str] = None,
    priority: int = 3,
) -> WaitlistEntry:
    """
    Add a patient to the waitlist.

    Returns the newly created WaitlistEntry.
    """
    if priority < 1 or priority > 5:
        raise ValueError("Priority must be between 1 and 5")

    entry = WaitlistEntry(
        practice_id=practice_id,
        patient_id=patient_id,
        patient_name=patient_name,
        patient_phone=patient_phone,
        appointment_type_id=appointment_type_id,
        preferred_date_start=preferred_date_start,
        preferred_date_end=preferred_date_end,
        preferred_time_start=preferred_time_start,
        preferred_time_end=preferred_time_end,
        notes=notes,
        priority=priority,
        status="waiting",
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)

    logger.info(
        "Patient '%s' added to waitlist for practice %s (entry %s)",
        patient_name, practice_id, entry.id,
    )
    return entry


# ---------------------------------------------------------------------------
# 2. Check waitlist on cancellation
# ---------------------------------------------------------------------------

async def check_waitlist_on_cancellation(
    db: AsyncSession,
    practice_id: UUID,
    appointment: Appointment,
) -> list[dict]:
    """
    When an appointment is cancelled, find matching waitlist entries and
    notify the highest-priority patients via SMS.

    Matching criteria:
    - Same practice
    - Status is 'waiting'
    - If appointment_type_id is set, it matches the cancelled appointment's type
    - If preferred_date_start/end is set, the cancelled date falls within range
    - If preferred_time_start/end is set, the cancelled time falls within range

    Notifies up to 3 matching patients (highest priority first, then oldest).

    Returns a list of notification result dicts.
    """
    cancelled_date = appointment.date
    cancelled_time = appointment.time

    # Build base query for waiting entries in this practice
    filters = [
        WaitlistEntry.practice_id == practice_id,
        WaitlistEntry.status == "waiting",
    ]

    stmt = (
        select(WaitlistEntry)
        .where(and_(*filters))
        .order_by(WaitlistEntry.priority.asc(), WaitlistEntry.created_at.asc())
    )
    result = await db.execute(stmt)
    candidates = result.scalars().all()

    # Filter candidates by matching criteria in Python (more flexible than SQL
    # for optional range fields)
    matching = []
    for entry in candidates:
        # Check appointment type match
        if entry.appointment_type_id and entry.appointment_type_id != appointment.appointment_type_id:
            continue

        # Check date range
        if entry.preferred_date_start and cancelled_date < entry.preferred_date_start:
            continue
        if entry.preferred_date_end and cancelled_date > entry.preferred_date_end:
            continue

        # Check time range
        if entry.preferred_time_start and cancelled_time < entry.preferred_time_start:
            continue
        if entry.preferred_time_end and cancelled_time > entry.preferred_time_end:
            continue

        matching.append(entry)

    # Notify up to 3 matching patients
    notifications = []
    for entry in matching[:3]:
        try:
            notify_result = await notify_waitlist_patient(
                db, entry, {
                    "date": cancelled_date,
                    "time": cancelled_time,
                    "appointment_type_id": appointment.appointment_type_id,
                }
            )
            notifications.append(notify_result)
        except Exception as e:
            logger.error(
                "Failed to notify waitlist entry %s: %s", entry.id, e,
            )
            notifications.append({
                "entry_id": str(entry.id),
                "success": False,
                "error": str(e),
            })

    return notifications


# ---------------------------------------------------------------------------
# 3. Notify waitlist patient
# ---------------------------------------------------------------------------

async def notify_waitlist_patient(
    db: AsyncSession,
    entry: WaitlistEntry,
    available_slot: dict,
) -> dict:
    """
    Send an SMS notification to a waitlist patient about an available slot.

    Updates the entry status to 'notified' and sets expiration to 2 hours.

    available_slot: {"date": date, "time": time, "appointment_type_id": UUID}
    """
    slot_date = available_slot["date"]
    slot_time = available_slot["time"]

    # Format date and time for the SMS
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_name = day_names[slot_date.weekday()]
    date_display = f"{day_name}, {slot_date.strftime('%B %d, %Y')}"

    # Format time as 12-hour
    hour = slot_time.hour
    minute = slot_time.minute
    period = "AM" if hour < 12 else "PM"
    display_hour = hour if hour <= 12 else hour - 12
    if display_hour == 0:
        display_hour = 12
    time_display = f"{display_hour}:{minute:02d} {period}"

    # Fetch practice name for the message
    practice_name = "the doctor's office"
    if entry.practice:
        practice_name = entry.practice.name or practice_name

    # Build SMS body
    first_name = entry.patient_name.split()[0] if entry.patient_name else "there"
    body = (
        f"Hi {first_name}, a slot opened up at {practice_name} "
        f"on {date_display} at {time_display}. "
        f"Reply YES to book or NO to pass. "
        f"This offer expires in 2 hours."
    )

    # Send SMS
    sms_result = await send_custom_sms(
        db=db,
        practice_id=entry.practice_id,
        to_number=entry.patient_phone,
        body=body,
    )

    # Update entry status
    now = datetime.now(timezone.utc)
    entry.status = "notified"
    entry.notified_at = now
    entry.expires_at = now + timedelta(hours=2)
    await db.flush()

    logger.info(
        "Waitlist notification sent to %s for entry %s (SMS success: %s)",
        entry.patient_phone, entry.id, sms_result.get("success"),
    )

    return {
        "entry_id": str(entry.id),
        "patient_name": entry.patient_name,
        "patient_phone": entry.patient_phone,
        "sms_success": sms_result.get("success", False),
        "message_sid": sms_result.get("message_sid"),
        "error": sms_result.get("error"),
    }


# ---------------------------------------------------------------------------
# 4. Process waitlist response (YES/NO SMS reply)
# ---------------------------------------------------------------------------

async def process_waitlist_response(
    db: AsyncSession,
    patient_phone: str,
    response: str,
) -> dict:
    """
    Handle a YES/NO SMS reply from a waitlist patient.

    Looks up the most recent 'notified' entry for this phone number
    that hasn't expired yet.

    - YES: Mark as 'booked' (actual booking is handled separately by staff
      or can be automated)
    - NO: Mark as 'cancelled' so the next person can be notified

    Returns a result dict with the action taken.
    """
    response = response.strip().upper()

    if response not in ("YES", "NO"):
        return {
            "success": False,
            "error": "Unrecognized response. Reply YES to book or NO to pass.",
        }

    now = datetime.now(timezone.utc)

    # Find the most recent notified entry for this phone number
    stmt = (
        select(WaitlistEntry)
        .where(
            and_(
                WaitlistEntry.patient_phone == patient_phone,
                WaitlistEntry.status == "notified",
                WaitlistEntry.expires_at > now,
            )
        )
        .order_by(WaitlistEntry.notified_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()

    if not entry:
        return {
            "success": False,
            "error": "No active waitlist notification found for this phone number.",
        }

    if response == "YES":
        entry.status = "booked"
        await db.flush()
        logger.info(
            "Waitlist entry %s marked as booked (patient replied YES)",
            entry.id,
        )
        return {
            "success": True,
            "action": "booked",
            "entry_id": str(entry.id),
            "patient_name": entry.patient_name,
            "message": "Appointment confirmed from waitlist.",
        }
    else:
        entry.status = "cancelled"
        await db.flush()
        logger.info(
            "Waitlist entry %s cancelled (patient replied NO)",
            entry.id,
        )
        return {
            "success": True,
            "action": "cancelled",
            "entry_id": str(entry.id),
            "patient_name": entry.patient_name,
            "message": "Waitlist spot declined.",
        }


# ---------------------------------------------------------------------------
# 5. Expire old entries
# ---------------------------------------------------------------------------

async def expire_old_entries(db: AsyncSession) -> int:
    """
    Mark all 'notified' waitlist entries as 'expired' if their expires_at
    has passed. Also expire 'waiting' entries whose preferred_date_end
    is in the past.

    Returns the number of entries expired.
    """
    now = datetime.now(timezone.utc)
    today = now.date()
    expired_count = 0

    # Expire notified entries past their expiration time
    stmt_notified = (
        update(WaitlistEntry)
        .where(
            and_(
                WaitlistEntry.status == "notified",
                WaitlistEntry.expires_at <= now,
            )
        )
        .values(status="expired")
    )
    result_notified = await db.execute(stmt_notified)
    expired_count += result_notified.rowcount

    # Expire waiting entries whose preferred date range has fully passed
    stmt_waiting = (
        update(WaitlistEntry)
        .where(
            and_(
                WaitlistEntry.status == "waiting",
                WaitlistEntry.preferred_date_end != None,  # noqa: E711
                WaitlistEntry.preferred_date_end < today,
            )
        )
        .values(status="expired")
    )
    result_waiting = await db.execute(stmt_waiting)
    expired_count += result_waiting.rowcount

    if expired_count > 0:
        await db.flush()
        logger.info("Expired %d waitlist entries", expired_count)

    return expired_count


# ---------------------------------------------------------------------------
# 6. Get waitlist stats
# ---------------------------------------------------------------------------

async def get_waitlist_stats(
    db: AsyncSession,
    practice_id: UUID,
) -> dict:
    """
    Return waitlist statistics for a practice:
    - total_waiting: count of entries with status 'waiting'
    - total_notified: count of entries with status 'notified'
    - total_booked: count of entries with status 'booked' (conversions)
    - total_expired: count of entries with status 'expired'
    - total_cancelled: count of entries with status 'cancelled'
    - avg_wait_hours: average time from created_at to notified_at for booked entries
    - conversion_rate: booked / (booked + expired + cancelled) as a percentage
    """
    base_filter = WaitlistEntry.practice_id == practice_id

    # Count by status
    status_stmt = (
        select(WaitlistEntry.status, func.count(WaitlistEntry.id))
        .where(base_filter)
        .group_by(WaitlistEntry.status)
    )
    status_result = await db.execute(status_stmt)
    status_counts = {row[0]: row[1] for row in status_result.all()}

    total_waiting = status_counts.get("waiting", 0)
    total_notified = status_counts.get("notified", 0)
    total_booked = status_counts.get("booked", 0)
    total_expired = status_counts.get("expired", 0)
    total_cancelled = status_counts.get("cancelled", 0)

    # Calculate average wait time for booked entries (created_at -> notified_at)
    avg_wait_hours = None
    booked_with_notification = (
        select(WaitlistEntry)
        .where(
            and_(
                base_filter,
                WaitlistEntry.status == "booked",
                WaitlistEntry.notified_at != None,  # noqa: E711
            )
        )
    )
    booked_result = await db.execute(booked_with_notification)
    booked_entries = booked_result.scalars().all()

    if booked_entries:
        total_wait = sum(
            (e.notified_at - e.created_at).total_seconds()
            for e in booked_entries
            if e.notified_at and e.created_at
        )
        avg_wait_hours = round(total_wait / len(booked_entries) / 3600, 1)

    # Conversion rate
    resolved_total = total_booked + total_expired + total_cancelled
    conversion_rate = round((total_booked / resolved_total) * 100, 1) if resolved_total > 0 else 0.0

    return {
        "total_waiting": total_waiting,
        "total_notified": total_notified,
        "total_booked": total_booked,
        "total_expired": total_expired,
        "total_cancelled": total_cancelled,
        "avg_wait_hours": avg_wait_hours,
        "conversion_rate": conversion_rate,
    }
