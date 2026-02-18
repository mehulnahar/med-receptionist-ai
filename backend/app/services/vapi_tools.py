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
from datetime import date, time, datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.patient import Patient
from app.models.appointment import Appointment
from app.models.appointment_type import AppointmentType
from app.models.practice_config import PracticeConfig
from app.services.booking_service import (
    find_or_create_patient,
    search_patients,
    get_available_slots,
    find_next_available_slot,
    book_appointment,
    cancel_appointment,
    reschedule_appointment,
)
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


async def _find_appointment_type_by_name(
    db: AsyncSession,
    practice_id: UUID,
    name: str,
) -> Optional[AppointmentType]:
    """Find an active appointment type by partial name match (case-insensitive)."""
    stmt = (
        select(AppointmentType)
        .where(
            and_(
                AppointmentType.practice_id == practice_id,
                AppointmentType.name.ilike(f"%{name}%"),
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
) -> Optional[Appointment]:
    """
    Find a patient's upcoming appointment.

    If appointment_date is provided, find the appointment on that specific date.
    Otherwise, find the next upcoming non-cancelled appointment from today onward.
    """
    filters = [
        Appointment.practice_id == practice_id,
        Appointment.patient_id == patient_id,
        Appointment.status != "cancelled",
    ]

    if appointment_date:
        filters.append(Appointment.date == appointment_date)
    else:
        filters.append(Appointment.date >= date.today())

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
        today = date.today()
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

        # --- Book ---
        appointment = await book_appointment(
            db,
            practice_id,
            patient_id=patient_id,
            appointment_type_id=appt_type.id,
            appt_date=appt_date,
            appt_time=appt_time,
            booked_by="ai",
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

        return {
            "success": True,
            "appointment_id": str(appointment.id),
            "patient_id": str(patient_id),
            "date": appointment.date.isoformat(),
            "time": appointment.time.strftime("%H:%M"),
            "patient_name": f"{patient.first_name} {patient.last_name}",
            "appointment_type": appt_type.name,
            "sms_sent": sms_sent,
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

        # Find the appointment to cancel
        appointment = await _find_upcoming_appointment(
            db, practice_id, patient_id, appointment_date
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

        # Link call if applicable
        if vapi_call_id:
            await link_call_to_patient(db, vapi_call_id, patient_id)

        return {
            "success": True,
            "cancelled_date": cancelled_appt.date.isoformat(),
            "cancelled_time": cancelled_appt.time.strftime("%H:%M"),
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

        # Find the existing appointment
        appointment = await _find_upcoming_appointment(
            db, practice_id, patient_id, old_date
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
# 9. Transfer to staff
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
    "transfer_to_staff": tool_transfer_to_staff,
}


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
    always receives a valid JSON response.
    """
    handler = TOOL_REGISTRY.get(tool_name)
    if not handler:
        logger.warning("dispatch_tool_call: Unknown tool '%s'", tool_name)
        return {"error": f"Unknown tool: {tool_name}"}

    try:
        sig = inspect.signature(handler)
        if "vapi_call_id" in sig.parameters:
            return await handler(db, practice_id, params, vapi_call_id=vapi_call_id)
        return await handler(db, practice_id, params)
    except Exception as e:
        logger.exception("Tool %s failed", tool_name)
        return {"error": f"Tool execution failed: {str(e)}"}
