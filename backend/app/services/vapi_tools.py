"""
Vapi Tool Function Implementations for the AI Medical Receptionist.

This module implements the 8 tool functions that Vapi's AI assistant calls
mid-conversation. Each function receives a database session, practice_id,
and a parameters dict from Vapi, and returns a result dict that Vapi feeds
back into the conversation.

All functions are async, practice-scoped, and wrapped in try/except to
guarantee Vapi always gets a valid JSON response (never an unhandled crash).
"""

import inspect
import logging
from datetime import date, time, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.patient import Patient
from app.models.appointment import Appointment
from app.models.appointment_type import AppointmentType
from app.models.practice import Practice
from app.models.practice_config import PracticeConfig
from app.models.schedule import ScheduleTemplate, ScheduleOverride
from app.models.voicemail import Voicemail
from app.services.booking_service import (
    find_or_create_patient,
    search_patients,
    get_available_slots,
    find_next_available_slot,
    book_appointment,
    cancel_appointment,
    reschedule_appointment,
)
from app.models.call import Call
from app.services.call_service import (
    link_call_to_patient,
    link_call_to_appointment,
    save_caller_info_to_call,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _parse_date(value: str) -> date:
    """Parse a YYYY-MM-DD date string."""
    return date.fromisoformat(value)


def _parse_time(value: str) -> time:
    """Parse a time string in HH:MM or HH:MM:SS format."""
    value = value.strip()
    if len(value) <= 5:
        return datetime.strptime(value, "%H:%M").time()
    return datetime.strptime(value, "%H:%M:%S").time()


def _esc_like(val: str) -> str:
    """Escape ILIKE wildcard characters (%, _, \\) in user-supplied input."""
    return val.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _find_appointment_type_by_name(
    db: AsyncSession,
    practice_id: UUID,
    name: str,
) -> Optional[AppointmentType]:
    """Find an active appointment type by partial name match (case-insensitive)."""
    escaped_name = _esc_like(name)
    stmt = (
        select(AppointmentType)
        .where(
            and_(
                AppointmentType.practice_id == practice_id,
                AppointmentType.name.ilike(f"%{escaped_name}%"),
                AppointmentType.is_active == True,  # noqa: E712
            )
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _get_first_active_appointment_type(
    db: AsyncSession,
    practice_id: UUID,
) -> Optional[AppointmentType]:
    """Return the first active appointment type for a practice (sorted by sort_order)."""
    stmt = (
        select(AppointmentType)
        .where(
            and_(
                AppointmentType.practice_id == practice_id,
                AppointmentType.is_active == True,  # noqa: E712
            )
        )
        .order_by(AppointmentType.sort_order)
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _find_upcoming_appointment(
    db: AsyncSession,
    practice_id: UUID,
    patient_id: UUID,
    appointment_date: Optional[date] = None,
    practice_tz: str = "America/New_York",
) -> Optional[Appointment]:
    """
    Find a patient's upcoming appointment.

    If appointment_date is provided, find the appointment on that specific date.
    Otherwise, find the next upcoming non-cancelled appointment from today onward
    using the practice's local timezone (not the server's UTC clock).
    """
    filters = [
        Appointment.practice_id == practice_id,
        Appointment.patient_id == patient_id,
        Appointment.status != "cancelled",
    ]

    if appointment_date:
        filters.append(Appointment.date == appointment_date)
    else:
        try:
            tz = ZoneInfo(practice_tz)
        except (KeyError, Exception):
            tz = ZoneInfo("America/New_York")
        today_in_practice_tz = datetime.now(tz).date()
        filters.append(Appointment.date >= today_in_practice_tz)

    stmt = (
        select(Appointment)
        .where(and_(*filters))
        .order_by(Appointment.date, Appointment.time)
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# 1. Check patient exists
# ---------------------------------------------------------------------------

async def tool_check_patient_exists(
    db: AsyncSession,
    practice_id: UUID,
    params: dict,
    vapi_call_id: Optional[str] = None,
) -> dict:
    """
    Look up whether a patient exists by first name, last name, and date of birth.

    params: {"first_name": str, "last_name": str, "dob": "YYYY-MM-DD"}
    """
    try:
        first_name = params["first_name"]
        last_name = params["last_name"]
        dob = _parse_date(params["dob"])

        patients = await search_patients(
            db,
            practice_id,
            first_name=first_name,
            last_name=last_name,
            dob=dob,
        )

        if not patients:
            return {"exists": False, "message": "Patient not found"}

        # Take the first (best) match
        patient = patients[0]

        # Link call to patient if we have a vapi_call_id
        if vapi_call_id:
            await link_call_to_patient(db, vapi_call_id, patient.id)

        return {
            "exists": True,
            "patient_id": str(patient.id),
            "name": f"{patient.first_name} {patient.last_name}",
            "phone": patient.phone or "",
            "insurance": patient.insurance_carrier or "",
        }

    except KeyError as e:
        logger.warning("tool_check_patient_exists: Missing required param %s", e)
        return {"exists": False, "error": f"Missing required parameter: {e}"}
    except Exception as e:
        logger.exception("tool_check_patient_exists failed")
        return {"exists": False, "error": f"Failed to check patient: {str(e)}"}


# ---------------------------------------------------------------------------
# 2. Get patient details
# ---------------------------------------------------------------------------

async def tool_get_patient_details(
    db: AsyncSession,
    practice_id: UUID,
    params: dict,
    vapi_call_id: Optional[str] = None,
) -> dict:
    """
    Fetch full patient details by patient ID.

    params: {"patient_id": "uuid"}
    """
    try:
        patient_id = UUID(params["patient_id"])

        stmt = select(Patient).where(
            and_(
                Patient.id == patient_id,
                Patient.practice_id == practice_id,
            )
        )
        result = await db.execute(stmt)
        patient = result.scalar_one_or_none()

        if not patient:
            return {"error": "Patient not found"}

        # Link call to patient if applicable
        if vapi_call_id:
            await link_call_to_patient(db, vapi_call_id, patient.id)

        return {
            "patient_id": str(patient.id),
            "name": f"{patient.first_name} {patient.last_name}",
            "first_name": patient.first_name,
            "last_name": patient.last_name,
            "dob": patient.dob.isoformat() if patient.dob else "",
            "phone": patient.phone or "",
            "address": patient.address or "",
            "insurance_carrier": patient.insurance_carrier or "",
            "member_id": patient.member_id or "",
            "group_number": patient.group_number or "",
            "referring_physician": patient.referring_physician or "",
            "is_new": patient.is_new,
        }

    except KeyError as e:
        logger.warning("tool_get_patient_details: Missing required param %s", e)
        return {"error": f"Missing required parameter: {e}"}
    except ValueError as e:
        logger.warning("tool_get_patient_details: Invalid patient_id format")
        return {"error": f"Invalid patient ID format: {str(e)}"}
    except Exception as e:
        logger.exception("tool_get_patient_details failed")
        return {"error": f"Failed to get patient details: {str(e)}"}


# ---------------------------------------------------------------------------
# 3. Check availability
# ---------------------------------------------------------------------------

async def tool_check_availability(
    db: AsyncSession,
    practice_id: UUID,
    params: dict,
) -> dict:
    """
    Check available appointment slots for a given date.

    params: {"date": "YYYY-MM-DD", "appointment_type": str (optional)}
    """
    DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    try:
        target_date = _parse_date(params["date"])

        # Use practice timezone for "today" instead of server time
        practice_tz_name = "America/New_York"  # default
        try:
            practice_row = (await db.execute(
                select(Practice.timezone).where(Practice.id == practice_id)
            )).scalar_one_or_none()
            if practice_row:
                practice_tz_name = practice_row
        except Exception:
            pass  # Fall back to default
        today = datetime.now(ZoneInfo(practice_tz_name)).date()
        appointment_type_id = None

        # If an appointment type name is provided, look it up
        appt_type_name = params.get("appointment_type")
        if appt_type_name:
            appt_type = await _find_appointment_type_by_name(
                db, practice_id, appt_type_name
            )
            if appt_type:
                appointment_type_id = appt_type.id

        # Prevent booking in the past
        if target_date < today:
            return {
                "date": target_date.isoformat(),
                "date_display": f"{DAY_NAMES[target_date.weekday()]}, {target_date.strftime('%B %d, %Y')}",
                "available_slots": [],
                "total_available": 0,
                "message": f"That date is in the past. Today is {DAY_NAMES[today.weekday()]}, {today.strftime('%B %d, %Y')}.",
                "today": today.isoformat(),
            }

        # Cap how far into the future a caller can check (use practice config)
        horizon_row = await db.execute(
            select(PracticeConfig.booking_horizon_days).where(
                PracticeConfig.practice_id == practice_id
            )
        )
        booking_horizon = horizon_row.scalar_one_or_none() or 90
        max_future = today + timedelta(days=booking_horizon)
        if target_date > max_future:
            return {
                "date": target_date.isoformat(),
                "date_display": f"{DAY_NAMES[target_date.weekday()]}, {target_date.strftime('%B %d, %Y')}",
                "available_slots": [],
                "total_available": 0,
                "message": f"We can only check availability up to {booking_horizon} days ahead. The latest date is {max_future.strftime('%B %d, %Y')}.",
                "today": today.isoformat(),
            }

        slots = await get_available_slots(
            db, practice_id, target_date, appointment_type_id
        )

        # Deduplicate and format slots as human-readable times
        seen = set()
        available_slots = []
        for s in slots:
            if s["is_available"]:
                time_str = s["time"].strftime("%H:%M")
                if time_str not in seen:
                    seen.add(time_str)
                    # Also provide 12-hour format for natural speech
                    hour = s["time"].hour
                    minute = s["time"].minute
                    period = "AM" if hour < 12 else "PM"
                    display_hour = hour if hour <= 12 else hour - 12
                    if display_hour == 0:
                        display_hour = 12
                    time_display = f"{display_hour}:{minute:02d} {period}" if minute else f"{display_hour} {period}"
                    available_slots.append(time_str)

        # Build the friendly date display
        day_name = DAY_NAMES[target_date.weekday()]
        date_display = f"{day_name}, {target_date.strftime('%B %d, %Y')}"
        if target_date == today:
            date_display = f"Today ({date_display})"
        elif target_date == today + timedelta(days=1):
            date_display = f"Tomorrow ({date_display})"

        if not available_slots:
            # Suggest trying the next working day
            return {
                "date": target_date.isoformat(),
                "date_display": date_display,
                "available_slots": [],
                "total_available": 0,
                "message": f"No availability on {date_display}. Please try another date.",
                "today": today.isoformat(),
            }

        return {
            "date": target_date.isoformat(),
            "date_display": date_display,
            "available_slots": available_slots,
            "total_available": len(available_slots),
            "today": today.isoformat(),
        }

    except KeyError as e:
        logger.warning("tool_check_availability: Missing required param %s", e)
        return {"error": f"Missing required parameter: {e}"}
    except Exception as e:
        logger.exception("tool_check_availability failed")
        return {"error": f"Failed to check availability: {str(e)}"}


# ---------------------------------------------------------------------------
# 4. Book appointment
# ---------------------------------------------------------------------------

async def tool_book_appointment(
    db: AsyncSession,
    practice_id: UUID,
    params: dict,
    vapi_call_id: Optional[str] = None,
) -> dict:
    """
    Book an appointment for a patient.

    params: {
        "first_name", "last_name", "dob",
        "phone" (optional), "address" (optional),
        "insurance_carrier" (optional), "member_id" (optional),
        "referring_physician" (optional),
        "accident_date" (optional), "accident_type" (optional),
        "appointment_type" (optional name), "date", "time",
        "patient_id" (optional uuid)
    }
    """
    try:
        # --- Resolve or create patient ---
        if params.get("patient_id"):
            patient_id = UUID(params["patient_id"])
            # Verify the patient belongs to this practice
            stmt = select(Patient).where(
                and_(
                    Patient.id == patient_id,
                    Patient.practice_id == practice_id,
                )
            )
            result = await db.execute(stmt)
            patient = result.scalar_one_or_none()
            if not patient:
                return {"success": False, "error": "Patient not found"}
        else:
            # Parse optional date fields for find_or_create_patient
            accident_date_val = None
            if params.get("accident_date"):
                accident_date_val = _parse_date(params["accident_date"])

            patient = await find_or_create_patient(
                db,
                practice_id,
                first_name=params["first_name"],
                last_name=params["last_name"],
                dob=_parse_date(params["dob"]),
                phone=params.get("phone"),
                address=params.get("address"),
                insurance_carrier=params.get("insurance_carrier"),
                member_id=params.get("member_id"),
                referring_physician=params.get("referring_physician"),
                accident_date=accident_date_val,
                accident_type=params.get("accident_type"),
            )
            patient_id = patient.id

        # --- Resolve appointment type ---
        appt_type = None
        appt_type_name = params.get("appointment_type")
        if appt_type_name:
            appt_type = await _find_appointment_type_by_name(
                db, practice_id, appt_type_name
            )

        # Fall back to the first active appointment type
        if not appt_type:
            appt_type = await _get_first_active_appointment_type(db, practice_id)

        if not appt_type:
            return {
                "success": False,
                "error": "No appointment types configured for this practice",
            }

        # --- Parse date and time ---
        appt_date = _parse_date(params["date"])
        appt_time = _parse_time(params["time"])

        # --- Resolve call_id from vapi_call_id ---
        resolved_call_id: Optional[UUID] = None
        if vapi_call_id:
            call_row = await db.execute(
                select(Call.id).where(Call.vapi_call_id == vapi_call_id)
            )
            resolved_call_id = call_row.scalar_one_or_none()

        # --- Book ---
        appointment = await book_appointment(
            db,
            practice_id,
            patient_id=patient_id,
            appointment_type_id=appt_type.id,
            appt_date=appt_date,
            appt_time=appt_time,
            booked_by="ai",
            call_id=resolved_call_id,
        )

        # --- Link call ---
        if vapi_call_id:
            await link_call_to_patient(db, vapi_call_id, patient_id)
            await link_call_to_appointment(db, vapi_call_id, appointment.id)

        # --- Auto-send SMS confirmation (non-blocking) ---
        sms_sent = False
        try:
            from app.services.sms_service import send_appointment_confirmation
            sms_result = await send_appointment_confirmation(
                db=db,
                practice_id=practice_id,
                appointment_id=appointment.id,
            )
            sms_sent = sms_result.get("success", False)
            if sms_sent:
                logger.info(
                    "SMS confirmation auto-sent for appointment %s (SID: %s)",
                    appointment.id, sms_result.get("message_sid"),
                )
            else:
                logger.info(
                    "SMS confirmation not sent for appointment %s: %s",
                    appointment.id, sms_result.get("error", "unknown"),
                )
        except Exception as sms_err:
            # SMS failure should never block the booking response
            logger.warning(
                "SMS auto-send failed for appointment %s: %s",
                appointment.id, sms_err,
            )

        # --- Auto-schedule appointment reminders (non-blocking) ---
        reminders_scheduled = 0
        try:
            from app.services.reminder_service import schedule_reminders
            reminders = await schedule_reminders(db, appointment)
            reminders_scheduled = len(reminders)
            if reminders_scheduled:
                logger.info(
                    "Auto-scheduled %d reminders for appointment %s",
                    reminders_scheduled, appointment.id,
                )
        except Exception as reminder_err:
            # Reminder scheduling failure should never block the booking response
            logger.warning(
                "Reminder auto-schedule failed for appointment %s: %s",
                appointment.id, reminder_err,
            )

        return {
            "success": True,
            "appointment_id": str(appointment.id),
            "patient_id": str(patient_id),
            "date": appointment.date.isoformat(),
            "time": appointment.time.strftime("%H:%M"),
            "patient_name": f"{patient.first_name} {patient.last_name}",
            "appointment_type": appt_type.name,
            "sms_sent": sms_sent,
            "reminders_scheduled": reminders_scheduled,
        }

    except KeyError as e:
        logger.warning("tool_book_appointment: Missing required param %s", e)
        return {"success": False, "error": f"Missing required parameter: {e}"}
    except ValueError as e:
        logger.warning("tool_book_appointment: Validation error: %s", e)
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception("tool_book_appointment failed")
        return {"success": False, "error": f"Failed to book appointment: {str(e)}"}


# ---------------------------------------------------------------------------
# 5. Verify insurance (real Stedi integration)
# ---------------------------------------------------------------------------

async def tool_verify_insurance(
    db: AsyncSession,
    practice_id: UUID,
    params: dict,
    vapi_call_id: Optional[str] = None,
) -> dict:
    """
    Verify a patient's insurance eligibility via the Stedi API.

    params: {
        "first_name", "last_name", "dob",
        "insurance_carrier", "member_id",
        "patient_id" (optional)
    }
    """
    try:
        from app.services.insurance_service import check_eligibility, resolve_payer_id
        from app.models.practice_config import PracticeConfig

        carrier = params.get("insurance_carrier", "")
        member_id_val = params.get("member_id", "")
        first_name = params.get("first_name", "")
        last_name = params.get("last_name", "")
        dob_str = params.get("dob", "")

        if not carrier or not member_id_val:
            return {
                "verified": False,
                "error": "Insurance carrier name and member ID are required",
            }

        # Check if Stedi is enabled for this practice
        config_stmt = select(PracticeConfig).where(
            PracticeConfig.practice_id == practice_id
        )
        config_result = await db.execute(config_stmt)
        practice_config = config_result.scalar_one_or_none()

        # If Stedi is not enabled, return a graceful acknowledgment
        if not practice_config or not practice_config.stedi_enabled:
            return {
                "verified": True,
                "carrier": carrier,
                "member_id": member_id_val,
                "message": (
                    "Insurance information has been recorded. "
                    "We'll verify coverage before your appointment."
                ),
            }

        # Resolve or create patient for the verification
        patient_id = None
        if params.get("patient_id"):
            patient_id = UUID(params["patient_id"])
        elif first_name and last_name and dob_str:
            # Try to find patient
            dob = _parse_date(dob_str)
            patients = await search_patients(
                db, practice_id, first_name=first_name, last_name=last_name, dob=dob
            )
            if patients:
                patient_id = patients[0].id

        if not patient_id:
            # Can't verify without a patient record
            return {
                "verified": True,
                "carrier": carrier,
                "member_id": member_id_val,
                "message": (
                    "Insurance information has been recorded. "
                    "We'll verify coverage before your appointment."
                ),
            }

        # Parse DOB
        dob = _parse_date(dob_str) if dob_str else None

        # Determine call_id UUID if we have a vapi_call_id
        call_id = None
        if vapi_call_id:
            from app.models.call import Call
            call_stmt = select(Call.id).where(Call.vapi_call_id == vapi_call_id)
            call_result = await db.execute(call_stmt)
            call_id = call_result.scalar_one_or_none()

        # Run the real eligibility check
        result = await check_eligibility(
            db=db,
            practice_id=practice_id,
            patient_id=patient_id,
            carrier_name=carrier,
            member_id=member_id_val,
            first_name=first_name,
            last_name=last_name,
            dob=dob,
            call_id=call_id,
        )

        # Build a conversational response for the AI
        if result.get("error"):
            return {
                "verified": False,
                "carrier": carrier,
                "member_id": member_id_val,
                "message": (
                    "I wasn't able to verify insurance coverage right now. "
                    "We'll verify it before your appointment."
                ),
                "error": result["error"],
            }

        if result.get("is_active"):
            parts = [f"Insurance with {result.get('carrier', carrier)} is active"]
            if result.get("copay"):
                parts.append(f"copay is ${result['copay']}")
            if result.get("plan_name"):
                parts.append(f"plan: {result['plan_name']}")
            return {
                "verified": True,
                "is_active": True,
                "carrier": result.get("carrier", carrier),
                "member_id": member_id_val,
                "copay": str(result["copay"]) if result.get("copay") else None,
                "plan_name": result.get("plan_name"),
                "message": ". ".join(parts),
            }
        else:
            return {
                "verified": True,
                "is_active": False,
                "carrier": result.get("carrier", carrier),
                "member_id": member_id_val,
                "message": (
                    f"Coverage with {result.get('carrier', carrier)} appears to be inactive. "
                    "Please bring your insurance card to your appointment so we can verify."
                ),
            }

    except Exception as e:
        logger.exception("tool_verify_insurance failed")
        return {
            "verified": False,
            "carrier": params.get("insurance_carrier", "Unknown"),
            "member_id": params.get("member_id", "Unknown"),
            "message": (
                "I wasn't able to verify insurance coverage right now. "
                "We'll verify it before your appointment."
            ),
            "error": f"Insurance verification failed: {str(e)}",
        }


# ---------------------------------------------------------------------------
# 6. Cancel appointment
# ---------------------------------------------------------------------------

async def tool_cancel_appointment(
    db: AsyncSession,
    practice_id: UUID,
    params: dict,
    vapi_call_id: Optional[str] = None,
) -> dict:
    """
    Cancel a patient's upcoming appointment.

    params: {"patient_id": "uuid", "appointment_date": "YYYY-MM-DD" (optional)}
    """
    try:
        patient_id = UUID(params["patient_id"])

        # Parse optional appointment date filter
        appointment_date = None
        if params.get("appointment_date"):
            appointment_date = _parse_date(params["appointment_date"])

        # Resolve practice timezone for "today" calculation
        practice_tz_name = "America/New_York"
        try:
            tz_row = (await db.execute(
                select(Practice.timezone).where(Practice.id == practice_id)
            )).scalar_one_or_none()
            if tz_row:
                practice_tz_name = tz_row
        except Exception:
            pass

        # Find the appointment to cancel
        appointment = await _find_upcoming_appointment(
            db, practice_id, patient_id, appointment_date,
            practice_tz=practice_tz_name,
        )

        if not appointment:
            return {
                "success": False,
                "error": "No upcoming appointment found for this patient",
            }

        # Cancel it
        cancelled_appt = await cancel_appointment(
            db,
            appointment_id=appointment.id,
            practice_id=practice_id,
            reason="Cancelled by patient via phone",
        )

        # Cancel pending reminders for the cancelled appointment
        try:
            from app.services.reminder_service import cancel_reminders
            await cancel_reminders(db, cancelled_appt.id)
        except Exception as rem_err:
            logger.warning("tool_cancel_appointment: failed to cancel reminders: %s", rem_err)

        # Link call if applicable
        if vapi_call_id:
            await link_call_to_patient(db, vapi_call_id, patient_id)

        # Check waitlist for patients who might want this newly opened slot
        waitlist_notified = 0
        try:
            from app.services.waitlist_service import check_waitlist_on_cancellation
            notifications = await check_waitlist_on_cancellation(
                db, practice_id, cancelled_appt,
            )
            waitlist_notified = sum(
                1 for n in notifications if n.get("sms_success")
            )
            if waitlist_notified:
                logger.info(
                    "Waitlist: notified %d patient(s) about cancelled slot on %s at %s",
                    waitlist_notified,
                    cancelled_appt.date.isoformat(),
                    cancelled_appt.time.strftime("%H:%M"),
                )
        except Exception as wl_err:
            # Waitlist notification failure should never block the cancellation response
            logger.warning(
                "Waitlist check failed after cancellation of appointment %s: %s",
                appointment.id, wl_err,
            )

        return {
            "success": True,
            "cancelled_date": cancelled_appt.date.isoformat(),
            "cancelled_time": cancelled_appt.time.strftime("%H:%M"),
            "waitlist_notified": waitlist_notified,
        }

    except KeyError as e:
        logger.warning("tool_cancel_appointment: Missing required param %s", e)
        return {"success": False, "error": f"Missing required parameter: {e}"}
    except ValueError as e:
        logger.warning("tool_cancel_appointment: Validation error: %s", e)
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception("tool_cancel_appointment failed")
        return {"success": False, "error": f"Failed to cancel appointment: {str(e)}"}


# ---------------------------------------------------------------------------
# 7. Reschedule appointment
# ---------------------------------------------------------------------------

async def tool_reschedule_appointment(
    db: AsyncSession,
    practice_id: UUID,
    params: dict,
    vapi_call_id: Optional[str] = None,
) -> dict:
    """
    Reschedule a patient's existing appointment to a new date and time.

    params: {
        "patient_id": "uuid",
        "old_date": "YYYY-MM-DD" (optional),
        "new_date": "YYYY-MM-DD",
        "new_time": "HH:MM"
    }
    """
    try:
        patient_id = UUID(params["patient_id"])

        # Parse optional old date
        old_date = None
        if params.get("old_date"):
            old_date = _parse_date(params["old_date"])

        # Resolve practice timezone for "today" calculation
        practice_tz_name = "America/New_York"
        try:
            tz_row = (await db.execute(
                select(Practice.timezone).where(Practice.id == practice_id)
            )).scalar_one_or_none()
            if tz_row:
                practice_tz_name = tz_row
        except Exception:
            pass

        # Find the existing appointment
        appointment = await _find_upcoming_appointment(
            db, practice_id, patient_id, old_date,
            practice_tz=practice_tz_name,
        )

        if not appointment:
            return {
                "success": False,
                "error": "No upcoming appointment found for this patient",
            }

        # Parse new date/time
        new_date = _parse_date(params["new_date"])
        new_time = _parse_time(params["new_time"])

        # Store old date/time before rescheduling
        old_appt_date = appointment.date.isoformat()
        old_appt_time = appointment.time.strftime("%H:%M")

        # Reschedule
        new_appointment = await reschedule_appointment(
            db,
            appointment_id=appointment.id,
            practice_id=practice_id,
            new_date=new_date,
            new_time=new_time,
        )

        # Cancel old reminders and schedule new ones
        try:
            from app.services.reminder_service import cancel_reminders, schedule_reminders
            await cancel_reminders(db, appointment.id)
            await schedule_reminders(db, new_appointment)
        except Exception as rem_err:
            logger.warning("tool_reschedule_appointment: failed to update reminders: %s", rem_err)

        # Link call if applicable
        if vapi_call_id:
            await link_call_to_patient(db, vapi_call_id, patient_id)
            await link_call_to_appointment(db, vapi_call_id, new_appointment.id)

        return {
            "success": True,
            "old_date": old_appt_date,
            "old_time": old_appt_time,
            "new_date": new_appointment.date.isoformat(),
            "new_time": new_appointment.time.strftime("%H:%M"),
            "appointment_id": str(new_appointment.id),
        }

    except KeyError as e:
        logger.warning("tool_reschedule_appointment: Missing required param %s", e)
        return {"success": False, "error": f"Missing required parameter: {e}"}
    except ValueError as e:
        logger.warning("tool_reschedule_appointment: Validation error: %s", e)
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception("tool_reschedule_appointment failed")
        return {
            "success": False,
            "error": f"Failed to reschedule appointment: {str(e)}",
        }


# ---------------------------------------------------------------------------
# 8. Save caller info (early data capture)
# ---------------------------------------------------------------------------

async def tool_save_caller_info(
    db: AsyncSession,
    practice_id: UUID,
    params: dict,
    vapi_call_id: Optional[str] = None,
) -> dict:
    """
    Save caller's name and phone number early in the conversation.

    This tool is called as soon as the AI collects the caller's name and
    phone number -- BEFORE the full booking flow. This ensures that even if
    the call drops, we have the caller's identity on record for callbacks.

    If the caller matches an existing patient, we link them immediately.
    If not, we still store name + phone on the call record.

    HIPAA-safe: This stores structured data via a tool call, not in
    transcripts. Works regardless of HIPAA mode.

    params: {
        "first_name": str,
        "last_name": str,
        "phone": str (optional -- the number the caller wants to be reached at),
        "dob": "YYYY-MM-DD" (optional -- if already collected),
        "reason": str (optional -- brief reason for calling)
    }
    """
    try:
        first_name = params.get("first_name", "").strip()
        last_name = params.get("last_name", "").strip()
        phone = params.get("phone", "").strip()
        dob_str = params.get("dob", "").strip()
        reason = params.get("reason", "").strip()

        if not first_name and not last_name:
            return {
                "saved": False,
                "error": "At least a first or last name is required",
            }

        caller_name = f"{first_name} {last_name}".strip()

        # Try to find an existing patient if we have enough info
        patient_id = None
        patient_found = False

        if first_name and last_name and dob_str:
            try:
                dob = _parse_date(dob_str)
                patients = await search_patients(
                    db, practice_id,
                    first_name=first_name,
                    last_name=last_name,
                    dob=dob,
                )
                if patients:
                    patient_id = patients[0].id
                    patient_found = True
            except (ValueError, Exception) as e:
                logger.warning("save_caller_info: patient lookup failed: %s", e)

        # Save to call record (name + phone + patient link)
        if vapi_call_id:
            await save_caller_info_to_call(
                db,
                vapi_call_id=vapi_call_id,
                caller_name=caller_name,
                caller_phone=phone if phone else None,
                patient_id=patient_id,
            )

        result = {
            "saved": True,
            "caller_name": caller_name,
            "is_existing_patient": patient_found,
        }

        if patient_found:
            result["patient_id"] = str(patient_id)
            result["message"] = f"Welcome back, {first_name}! I found your record."
        else:
            result["message"] = f"Thank you, {first_name}. I've noted your information."

        if reason:
            result["reason"] = reason

        return result

    except Exception as e:
        logger.exception("tool_save_caller_info failed")
        return {"saved": False, "error": f"Failed to save caller info: {str(e)}"}


# ---------------------------------------------------------------------------
# 9. Request prescription refill
# ---------------------------------------------------------------------------

async def tool_request_refill(
    db: AsyncSession,
    practice_id: UUID,
    params: dict,
    vapi_call_id: Optional[str] = None,
) -> dict:
    """
    Submit a prescription refill request.

    params: {
        "medication_name": str (required),
        "dosage": str (optional),
        "pharmacy_name": str (optional),
        "pharmacy_phone": str (optional),
        "patient_id": str (optional uuid),
        "caller_name": str (optional)
    }
    """
    try:
        from app.models.refill_request import RefillRequest
        from app.models.call import Call

        medication_name = params.get("medication_name", "").strip()
        if not medication_name:
            return {"success": False, "error": "Medication name is required"}

        dosage = params.get("dosage", "").strip() or None
        pharmacy_name = params.get("pharmacy_name", "").strip() or None
        pharmacy_phone = params.get("pharmacy_phone", "").strip() or None
        caller_name = params.get("caller_name", "").strip() or None

        # Resolve patient_id if provided
        patient_id = None
        if params.get("patient_id"):
            try:
                patient_id = UUID(params["patient_id"])
            except (ValueError, AttributeError):
                logger.warning("tool_request_refill: Invalid patient_id format")

        # Resolve call_id from vapi_call_id
        call_id = None
        caller_phone = None
        if vapi_call_id:
            call_stmt = select(Call).where(Call.vapi_call_id == vapi_call_id)
            call_result = await db.execute(call_stmt)
            call_record = call_result.scalar_one_or_none()
            if call_record:
                call_id = call_record.id
                caller_phone = call_record.caller_phone
                # If no patient_id provided, try from call record
                if not patient_id and call_record.patient_id:
                    patient_id = call_record.patient_id

        refill = RefillRequest(
            practice_id=practice_id,
            patient_id=patient_id,
            call_id=call_id,
            medication_name=medication_name,
            dosage=dosage,
            pharmacy_name=pharmacy_name,
            pharmacy_phone=pharmacy_phone,
            caller_name=caller_name,
            caller_phone=caller_phone,
            status="pending",
            urgency="normal",
        )
        db.add(refill)
        await db.flush()

        logger.info(
            "Refill request created: id=%s, medication=%s, practice=%s",
            refill.id, medication_name, practice_id,
        )

        return {
            "success": True,
            "refill_id": str(refill.id),
            "medication_name": medication_name,
            "message": (
                f"Your prescription refill request for {medication_name} has been submitted. "
                "The doctor's office will review it and process it within 24 to 48 hours."
            ),
        }

    except KeyError as e:
        logger.warning("tool_request_refill: Missing required param %s", e)
        return {"success": False, "error": f"Missing required parameter: {e}"}
    except Exception as e:
        logger.exception("tool_request_refill failed")
        return {"success": False, "error": f"Failed to submit refill request: {str(e)}"}


# ---------------------------------------------------------------------------
# 10. Transfer to staff
# ---------------------------------------------------------------------------

async def tool_transfer_to_staff(
    db: AsyncSession,
    practice_id: UUID,
    params: dict,
) -> dict:
    """
    Request a live transfer to office staff.

    params: {"reason": str}
    """
    try:
        reason = params.get("reason", "Caller requested staff transfer")

        # Fetch practice config to get the transfer number
        stmt = select(PracticeConfig).where(
            PracticeConfig.practice_id == practice_id
        )
        result = await db.execute(stmt)
        config = result.scalar_one_or_none()

        if not config or not config.transfer_number:
            return {
                "transfer": False,
                "message": (
                    "No staff transfer number configured. "
                    "Please call back during office hours."
                ),
            }

        return {
            "transfer": True,
            "number": config.transfer_number,
            "reason": reason,
        }

    except Exception as e:
        logger.exception("tool_transfer_to_staff failed")
        return {
            "transfer": False,
            "error": f"Failed to initiate transfer: {str(e)}",
        }


# ---------------------------------------------------------------------------
# 11. Check office hours
# ---------------------------------------------------------------------------

async def tool_check_office_hours(
    db: AsyncSession,
    practice_id: UUID,
    params: dict,
) -> dict:
    """
    Check if the office is currently open based on the practice's schedule.

    Uses ScheduleTemplate for regular weekly hours and ScheduleOverride for
    date-specific overrides (holidays, special closures, etc.).

    params: {} (no parameters required)
    """
    DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    try:
        # Use practice timezone for accurate open/closed determination
        from zoneinfo import ZoneInfo
        from app.models.practice import Practice as PracticeModel

        tz_row = (await db.execute(
            select(PracticeModel.timezone).where(PracticeModel.id == practice_id)
        )).scalar_one_or_none()
        practice_tz = ZoneInfo(tz_row) if tz_row else ZoneInfo("America/New_York")
        now = datetime.now(practice_tz)
        current_day = now.weekday()  # 0=Monday, 6=Sunday
        current_time_val = now.time()
        today_date = now.date()

        # Check for a date-specific override first
        override_stmt = select(ScheduleOverride).where(
            and_(
                ScheduleOverride.practice_id == practice_id,
                ScheduleOverride.date == today_date,
            )
        )
        override_result = await db.execute(override_stmt)
        override = override_result.scalar_one_or_none()

        is_open = False
        today_start = None
        today_end = None
        override_reason = None

        if override:
            # Override takes precedence
            if override.is_working and override.start_time and override.end_time:
                today_start = override.start_time
                today_end = override.end_time
                is_open = today_start <= current_time_val <= today_end
            else:
                # Explicitly closed (holiday, etc.)
                is_open = False
                override_reason = override.reason or "Office closed (schedule override)"
        else:
            # Fall back to the regular weekly schedule template
            template_stmt = select(ScheduleTemplate).where(
                and_(
                    ScheduleTemplate.practice_id == practice_id,
                    ScheduleTemplate.day_of_week == current_day,
                )
            )
            template_result = await db.execute(template_stmt)
            template = template_result.scalar_one_or_none()

            if template and template.is_enabled and template.start_time and template.end_time:
                today_start = template.start_time
                today_end = template.end_time
                is_open = today_start <= current_time_val <= today_end
            else:
                is_open = False

        # Find next open time for the response
        next_open = None
        next_open_day = None
        if not is_open:
            # If we're before today's opening, next open is today
            if today_start and current_time_val < today_start:
                next_open = today_start.strftime("%H:%M")
                next_open_day = DAY_NAMES[current_day]
            else:
                # Search the next 7 days
                for offset in range(1, 8):
                    check_date = today_date + timedelta(days=offset)
                    check_day = check_date.weekday()

                    # Check override for that date
                    fut_override_stmt = select(ScheduleOverride).where(
                        and_(
                            ScheduleOverride.practice_id == practice_id,
                            ScheduleOverride.date == check_date,
                        )
                    )
                    fut_override_result = await db.execute(fut_override_stmt)
                    fut_override = fut_override_result.scalar_one_or_none()

                    if fut_override:
                        if fut_override.is_working and fut_override.start_time:
                            next_open = fut_override.start_time.strftime("%H:%M")
                            next_open_day = DAY_NAMES[check_day]
                            break
                        continue  # explicitly closed that day

                    # Check regular template
                    fut_template_stmt = select(ScheduleTemplate).where(
                        and_(
                            ScheduleTemplate.practice_id == practice_id,
                            ScheduleTemplate.day_of_week == check_day,
                        )
                    )
                    fut_template_result = await db.execute(fut_template_stmt)
                    fut_template = fut_template_result.scalar_one_or_none()

                    if fut_template and fut_template.is_enabled and fut_template.start_time:
                        next_open = fut_template.start_time.strftime("%H:%M")
                        next_open_day = DAY_NAMES[check_day]
                        break

        # Build regular hours summary from templates
        schedule_stmt = (
            select(ScheduleTemplate)
            .where(
                and_(
                    ScheduleTemplate.practice_id == practice_id,
                    ScheduleTemplate.is_enabled == True,  # noqa: E712
                )
            )
            .order_by(ScheduleTemplate.day_of_week)
        )
        schedule_result = await db.execute(schedule_stmt)
        templates = schedule_result.scalars().all()

        regular_hours = []
        for t in templates:
            if t.start_time and t.end_time:
                regular_hours.append(
                    f"{DAY_NAMES[t.day_of_week]}: {t.start_time.strftime('%H:%M')} - {t.end_time.strftime('%H:%M')}"
                )

        result = {
            "is_open": is_open,
            "current_day": DAY_NAMES[current_day],
            "current_time": current_time_val.strftime("%H:%M"),
            "regular_hours": regular_hours,
        }

        if today_start and today_end:
            result["today_hours"] = f"{today_start.strftime('%H:%M')} - {today_end.strftime('%H:%M')}"

        if override_reason:
            result["closure_reason"] = override_reason

        if next_open and next_open_day:
            result["next_open"] = f"{next_open_day} at {next_open}"

        return result

    except Exception as e:
        logger.exception("tool_check_office_hours failed")
        return {
            "is_open": None,
            "error": f"Failed to check office hours: {str(e)}",
            "message": "I'm unable to verify our current hours right now. Please call back or check our website.",
        }


# ---------------------------------------------------------------------------
# 12. Leave voicemail
# ---------------------------------------------------------------------------

async def tool_leave_voicemail(
    db: AsyncSession,
    practice_id: UUID,
    params: dict,
    vapi_call_id: Optional[str] = None,
) -> dict:
    """
    Record a voicemail message from a caller when the office is closed
    or staff is unavailable.

    params: {
        "message": str (required),
        "caller_name": str (optional),
        "caller_phone": str (optional),
        "urgency": str (optional, "normal" or "urgent"),
        "callback_requested": bool (optional, default True),
        "preferred_callback_time": str (optional),
        "reason": str (optional),
        "patient_id": str (optional uuid)
    }
    """
    try:
        message_text = params.get("message", "").strip()
        if not message_text:
            return {"success": False, "error": "Message is required"}

        caller_name = params.get("caller_name", "").strip() or None
        caller_phone = params.get("caller_phone", "").strip() or None
        urgency = params.get("urgency", "normal").strip()
        if urgency not in ("normal", "urgent", "emergency"):
            urgency = "normal"
        callback_requested = params.get("callback_requested", True)
        preferred_callback_time = params.get("preferred_callback_time", "").strip() or None
        reason = params.get("reason", "").strip() or None

        # Resolve patient_id if provided
        patient_id = None
        if params.get("patient_id"):
            try:
                patient_id = UUID(params["patient_id"])
            except (ValueError, AttributeError):
                logger.warning("tool_leave_voicemail: Invalid patient_id format")

        # Resolve call_id from vapi_call_id
        call_id = None
        if vapi_call_id:
            from app.models.call import Call
            call_stmt = select(Call).where(Call.vapi_call_id == vapi_call_id)
            call_result = await db.execute(call_stmt)
            call_record = call_result.scalar_one_or_none()
            if call_record:
                call_id = call_record.id
                # Use caller info from the call record if not provided
                if not caller_phone and call_record.caller_phone:
                    caller_phone = call_record.caller_phone
                if not caller_name and call_record.caller_name:
                    caller_name = call_record.caller_name
                # Link patient from call if not provided
                if not patient_id and call_record.patient_id:
                    patient_id = call_record.patient_id

        # Truncate message to prevent unbounded storage from AI-generated content
        safe_message = message_text[:10000] if message_text and len(message_text) > 10000 else message_text
        safe_reason = reason[:500] if reason and len(reason) > 500 else reason

        voicemail = Voicemail(
            practice_id=practice_id,
            call_id=call_id,
            patient_id=patient_id,
            caller_name=caller_name,
            caller_phone=caller_phone,
            message=safe_message,
            urgency=urgency,
            callback_requested=callback_requested,
            preferred_callback_time=preferred_callback_time,
            reason=safe_reason,
            status="new",
        )
        db.add(voicemail)
        await db.flush()

        logger.info(
            "Voicemail created: id=%s, practice=%s, urgency=%s",
            voicemail.id, practice_id, urgency,
        )

        return {
            "success": True,
            "voicemail_id": str(voicemail.id),
            "message": (
                "Your message has been saved. "
                "Someone from our office will get back to you when we reopen."
            ),
        }

    except Exception as e:
        logger.exception("tool_leave_voicemail failed")
        return {"success": False, "error": f"Failed to save voicemail: {str(e)}"}


# ---------------------------------------------------------------------------
# 13. Add to waitlist
# ---------------------------------------------------------------------------

async def tool_add_to_waitlist(
    db: AsyncSession,
    practice_id: UUID,
    params: dict,
    vapi_call_id: Optional[str] = None,
) -> dict:
    """
    Add a patient to the waitlist when no slots are available and the
    patient wants the earliest possible appointment.

    params: {
        "patient_name": str (required),
        "patient_phone": str (required),
        "appointment_type": str (optional - name of appointment type),
        "preferred_dates": str (optional - e.g. "next week", "Monday-Friday"),
        "notes": str (optional)
    }
    """
    try:
        from app.services.waitlist_service import add_to_waitlist

        patient_name = params.get("patient_name", "").strip()
        patient_phone = params.get("patient_phone", "").strip()

        if not patient_name:
            return {"success": False, "error": "Patient name is required"}
        if not patient_phone:
            return {"success": False, "error": "Patient phone number is required"}

        notes = params.get("notes", "").strip() or None
        preferred_dates = params.get("preferred_dates", "").strip()

        # Try to resolve appointment type by name
        appointment_type_id = None
        appt_type_name = params.get("appointment_type")
        if appt_type_name:
            appt_type = await _find_appointment_type_by_name(
                db, practice_id, appt_type_name
            )
            if appt_type:
                appointment_type_id = appt_type.id

        # Try to find existing patient by name + phone
        patient_id = None
        if vapi_call_id:
            from app.models.call import Call
            call_stmt = select(Call).where(Call.vapi_call_id == vapi_call_id)
            call_result = await db.execute(call_stmt)
            call_record = call_result.scalar_one_or_none()
            if call_record and call_record.patient_id:
                patient_id = call_record.patient_id

        # Build notes with preferred dates context if provided
        full_notes = notes or ""
        if preferred_dates:
            pref_note = f"Preferred dates: {preferred_dates}"
            full_notes = f"{full_notes}\n{pref_note}".strip() if full_notes else pref_note

        entry = await add_to_waitlist(
            db=db,
            practice_id=practice_id,
            patient_name=patient_name,
            patient_phone=patient_phone,
            patient_id=patient_id,
            appointment_type_id=appointment_type_id,
            notes=full_notes if full_notes else None,
        )

        return {
            "success": True,
            "waitlist_id": str(entry.id),
            "patient_name": patient_name,
            "message": (
                f"I've added {patient_name.split()[0]} to our waitlist. "
                "If a slot opens up, we'll send a text message to confirm. "
                "Is there anything else I can help you with?"
            ),
        }

    except ValueError as e:
        logger.warning("tool_add_to_waitlist: Validation error: %s", e)
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception("tool_add_to_waitlist failed")
        return {"success": False, "error": f"Failed to add to waitlist: {str(e)}"}


# ---------------------------------------------------------------------------
# Tool Registry and Dispatcher
# ---------------------------------------------------------------------------

TOOL_REGISTRY = {
    "save_caller_info": tool_save_caller_info,
    "check_patient_exists": tool_check_patient_exists,
    "get_patient_details": tool_get_patient_details,
    "check_availability": tool_check_availability,
    "book_appointment": tool_book_appointment,
    "verify_insurance": tool_verify_insurance,
    "cancel_appointment": tool_cancel_appointment,
    "reschedule_appointment": tool_reschedule_appointment,
    "request_refill": tool_request_refill,
    "transfer_to_staff": tool_transfer_to_staff,
    "check_office_hours": tool_check_office_hours,
    "leave_voicemail": tool_leave_voicemail,
    "add_to_waitlist": tool_add_to_waitlist,
}


TOOL_CALL_TIMEOUT_SECONDS = 15  # Keep short — caller is waiting on a live voice call


async def dispatch_tool_call(
    db: AsyncSession,
    practice_id: UUID,
    tool_name: str,
    params: dict,
    vapi_call_id: Optional[str] = None,
) -> dict:
    """
    Central dispatcher that routes a Vapi tool call to the correct handler.

    Automatically detects whether the handler accepts a vapi_call_id parameter
    and passes it only when supported. Catches any unhandled exceptions so Vapi
    always receives a valid JSON response. Enforces a timeout to prevent
    hung tool calls from freezing the live conversation.
    """
    import asyncio

    handler = TOOL_REGISTRY.get(tool_name)
    if not handler:
        logger.warning("dispatch_tool_call: Unknown tool '%s'", tool_name)
        return {"error": f"Unknown tool: {tool_name}"}

    try:
        sig = inspect.signature(handler)
        if "vapi_call_id" in sig.parameters:
            coro = handler(db, practice_id, params, vapi_call_id=vapi_call_id)
        else:
            coro = handler(db, practice_id, params)

        return await asyncio.wait_for(coro, timeout=TOOL_CALL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.error(
            "Tool %s timed out after %ds (call=%s)",
            tool_name, TOOL_CALL_TIMEOUT_SECONDS, vapi_call_id,
        )
        return {"error": f"Tool {tool_name} timed out. Please try again."}
    except Exception as e:
        logger.exception("Tool %s failed", tool_name)
        return {"error": f"Tool execution failed: {str(e)}"}
