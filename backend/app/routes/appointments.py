"""Appointment booking endpoints — book, cancel, reschedule, confirm, and list."""

import logging
from uuid import UUID
from datetime import date, time as time_type

from fastapi import APIRouter, Depends, Header, HTTPException, status, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.appointment import Appointment
from app.models.patient import Patient
from app.models.appointment_type import AppointmentType

logger = logging.getLogger(__name__)
from app.schemas.appointment import (
    APPOINTMENT_STATUSES,
    BookAppointmentRequest,
    AppointmentResponse,
    AppointmentListResponse,
    CancelAppointmentRequest,
    RescheduleAppointmentRequest,
    ConfirmAppointmentRequest,
    AppointmentStatusUpdate,
)
from app.schemas.common import MessageResponse
from app.middleware.auth import get_current_user, require_any_staff, require_practice_admin
from app.services.booking_service import (
    book_appointment,
    cancel_appointment,
    reschedule_appointment,
    confirm_appointment,
    get_appointments,
    find_next_available_slot,
)

router = APIRouter()


def _ensure_practice(user: User) -> UUID:
    """Return the user's practice_id or raise 400 if it is None."""
    if not user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )
    return user.practice_id


def build_appointment_response(appt: Appointment) -> dict:
    """Build a dict suitable for constructing an AppointmentResponse.

    The Appointment model uses ``lazy="selectin"`` for relationships so
    ``appt.patient`` and ``appt.appointment_type`` are eagerly loaded.
    """
    data = {
        "id": appt.id,
        "practice_id": appt.practice_id,
        "patient_id": appt.patient_id,
        "appointment_type_id": appt.appointment_type_id,
        "date": appt.date,
        "time": appt.time,
        "duration_minutes": appt.duration_minutes,
        "status": appt.status,
        "insurance_verified": appt.insurance_verified,
        "insurance_verification_result": appt.insurance_verification_result,
        "booked_by": appt.booked_by,
        "call_id": appt.call_id,
        "notes": appt.notes,
        "sms_confirmation_sent": appt.sms_confirmation_sent,
        "entered_in_ehr_at": appt.entered_in_ehr_at,
        "entered_in_ehr_by": appt.entered_in_ehr_by,
        "created_at": appt.created_at,
        "updated_at": appt.updated_at,
        "patient_name": (
            f"{appt.patient.first_name} {appt.patient.last_name}"
            if appt.patient
            else "Unknown"
        ),
        "appointment_type_name": (
            appt.appointment_type.name if appt.appointment_type else "Unknown"
        ),
    }
    return data


# ---------------------------------------------------------------------------
# Book appointment
# ---------------------------------------------------------------------------


@router.post("/book", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
async def book_appointment_endpoint(
    request: BookAppointmentRequest,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
    x_idempotency_key: str | None = Header(None),
):
    """Book a new appointment for a patient.

    Accepts an optional ``X-Idempotency-Key`` header. When provided, if an
    appointment already exists for the same practice + call_id + patient +
    date + time, the existing appointment is returned instead of creating a
    duplicate.
    """
    practice_id = _ensure_practice(current_user)

    # Idempotency check: if a key is provided, look for a matching appointment.
    # Works with or without call_id — key uniqueness is based on
    # practice + patient + date + time (+ call_id when present).
    if x_idempotency_key:
        idem_filters = [
            Appointment.practice_id == practice_id,
            Appointment.patient_id == request.patient_id,
            Appointment.date == request.date,
            Appointment.time == request.time,
            Appointment.status.notin_(["cancelled", "no_show"]),
        ]
        if request.call_id:
            idem_filters.append(Appointment.call_id == request.call_id)
        existing_stmt = select(Appointment).where(and_(*idem_filters)).limit(1)
        existing_result = await db.execute(existing_stmt)
        existing_appt = existing_result.scalar_one_or_none()
        if existing_appt:
            logger.info(
                "Idempotent booking: returning existing appointment %s for key=%s",
                existing_appt.id, x_idempotency_key,
            )
            return AppointmentResponse(**build_appointment_response(existing_appt))

    try:
        appt = await book_appointment(
            db=db,
            practice_id=practice_id,
            patient_id=request.patient_id,
            appointment_type_id=request.appointment_type_id,
            appt_date=request.date,
            appt_time=request.time,
            notes=request.notes,
            booked_by=request.booked_by,
            call_id=request.call_id,
        )
    except ValueError as exc:
        error_msg = str(exc)
        # Use 409 for conflicts (double-booking), 400 for validation errors
        if "conflict" in error_msg.lower() or "already booked" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_msg,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    # Auto-send SMS confirmation (non-blocking — failure doesn't affect response)
    try:
        from app.services.sms_service import send_appointment_confirmation
        await send_appointment_confirmation(
            db=db,
            practice_id=practice_id,
            appointment_id=appt.id,
        )
    except Exception as sms_err:
        logger.warning("SMS auto-send failed for appointment %s: %s", appt.id, sms_err)

    # Auto-schedule appointment reminders (non-blocking)
    try:
        from app.services.reminder_service import schedule_reminders
        await schedule_reminders(db, appt)
    except Exception as reminder_err:
        logger.warning("Reminder auto-schedule failed for appointment %s: %s", appt.id, reminder_err)

    # Refresh so response reflects SMS/reminder updates (e.g. sms_confirmation_sent)
    await db.refresh(appt)

    return AppointmentResponse(**build_appointment_response(appt))


# ---------------------------------------------------------------------------
# List appointments
# ---------------------------------------------------------------------------


@router.get("/", response_model=AppointmentListResponse)
async def list_appointments(
    from_date: date | None = Query(None, description="Filter from this date"),
    to_date: date | None = Query(None, description="Filter up to this date"),
    patient_id: UUID | None = Query(None, description="Filter by patient"),
    appointment_status: str | None = Query(None, alias="status", description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """List appointments for the current practice with optional filters."""
    practice_id = _ensure_practice(current_user)

    if appointment_status and appointment_status not in APPOINTMENT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(APPOINTMENT_STATUSES)}",
        )

    try:
        appointments, total = await get_appointments(
            db=db,
            practice_id=practice_id,
            from_date=from_date,
            to_date=to_date,
            patient_id=patient_id,
            status_filter=appointment_status,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return AppointmentListResponse(
        appointments=[
            AppointmentResponse(**build_appointment_response(a))
            for a in appointments
        ],
        total=total,
    )


# ---------------------------------------------------------------------------
# Next available slot
# ---------------------------------------------------------------------------


@router.get("/next-available")
async def next_available_slot(
    appointment_type_id: UUID | None = Query(None, description="Appointment type to search for"),
    from_date: date | None = Query(None, description="Start searching from this date"),
    preferred_time: str | None = Query(None, description="Preferred time (HH:MM)"),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Find the next available appointment slot."""
    practice_id = _ensure_practice(current_user)

    # Convert preferred_time string to time object if provided
    pref_time = None
    if preferred_time:
        try:
            parts = preferred_time.split(":")
            pref_time = time_type(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="preferred_time must be in HH:MM format",
            )

    try:
        slot = await find_next_available_slot(
            db=db,
            practice_id=practice_id,
            appointment_type_id=appointment_type_id,
            from_date=from_date,
            preferred_time=pref_time,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    if not slot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No available slots found in the search range",
        )

    return slot


# ---------------------------------------------------------------------------
# Get single appointment
# ---------------------------------------------------------------------------


@router.get("/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment(
    appointment_id: UUID,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Get appointment details by ID, scoped to the current practice."""
    practice_id = _ensure_practice(current_user)

    result = await db.execute(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.practice_id == practice_id,
        )
    )
    appt = result.scalar_one_or_none()

    if not appt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )

    return AppointmentResponse(**build_appointment_response(appt))


# ---------------------------------------------------------------------------
# Cancel appointment
# ---------------------------------------------------------------------------


@router.put("/{appointment_id}/cancel", response_model=AppointmentResponse)
async def cancel_appointment_endpoint(
    appointment_id: UUID,
    request: CancelAppointmentRequest,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Cancel an existing appointment."""
    practice_id = _ensure_practice(current_user)

    try:
        appt = await cancel_appointment(
            db=db,
            practice_id=practice_id,
            appointment_id=appointment_id,
            reason=request.reason,
        )
    except ValueError as exc:
        error_msg = str(exc)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    # Cancel pending reminders for the cancelled appointment
    try:
        from app.services.reminder_service import cancel_reminders
        await cancel_reminders(db, appointment_id)
    except Exception as reminder_err:
        logger.warning("Failed to cancel reminders for appointment %s: %s", appointment_id, reminder_err)

    # Notify waitlisted patients about the newly-opened slot
    try:
        from app.services.waitlist_service import check_waitlist_on_cancellation
        await check_waitlist_on_cancellation(db, practice_id, appt)
    except Exception as wl_err:
        logger.warning("Failed to check waitlist after cancellation of %s: %s", appointment_id, wl_err)

    return AppointmentResponse(**build_appointment_response(appt))


# ---------------------------------------------------------------------------
# Confirm appointment
# ---------------------------------------------------------------------------


@router.put("/{appointment_id}/confirm", response_model=AppointmentResponse)
async def confirm_appointment_endpoint(
    appointment_id: UUID,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Confirm an appointment (e.g. patient confirmed via SMS or call)."""
    practice_id = _ensure_practice(current_user)

    try:
        appt = await confirm_appointment(
            db=db,
            practice_id=practice_id,
            appointment_id=appointment_id,
        )
    except ValueError as exc:
        error_msg = str(exc)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    return AppointmentResponse(**build_appointment_response(appt))


# ---------------------------------------------------------------------------
# Reschedule appointment
# ---------------------------------------------------------------------------


@router.put("/{appointment_id}/reschedule", response_model=AppointmentResponse)
async def reschedule_appointment_endpoint(
    appointment_id: UUID,
    request: RescheduleAppointmentRequest,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Reschedule an appointment to a new date/time. Returns the new appointment."""
    practice_id = _ensure_practice(current_user)

    try:
        new_appt = await reschedule_appointment(
            db=db,
            practice_id=practice_id,
            appointment_id=appointment_id,
            new_date=request.new_date,
            new_time=request.new_time,
            notes=request.notes,
        )
    except ValueError as exc:
        error_msg = str(exc)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg,
            )
        if "conflict" in error_msg.lower() or "already booked" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_msg,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    # Cancel old reminders and schedule new ones for the rescheduled appointment
    try:
        from app.services.reminder_service import cancel_reminders, schedule_reminders
        await cancel_reminders(db, appointment_id)
        await schedule_reminders(db, new_appt)
    except Exception as reminder_err:
        logger.warning("Failed to update reminders for rescheduled appointment %s: %s", appointment_id, reminder_err)

    return AppointmentResponse(**build_appointment_response(new_appt))


@router.patch("/{appointment_id}/status", response_model=AppointmentResponse)
async def update_appointment_status(
    appointment_id: UUID,
    request: AppointmentStatusUpdate,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Update the status of an appointment (e.g. no_show, entered_in_ehr, completed)."""
    from datetime import datetime, timezone

    practice_id = _ensure_practice(current_user)

    result = await db.execute(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.practice_id == practice_id,
        )
    )
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )

    appt.status = request.status
    if request.notes is not None:
        appt.notes = request.notes

    await db.commit()
    await db.refresh(appt)
    return AppointmentResponse(**build_appointment_response(appt))
