"""
Core booking service for the AI Medical Receptionist.

Handles patient lookup/creation, schedule availability, appointment booking,
cancellation, rescheduling, and confirmation. All operations are practice-scoped
for multi-tenant security.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from uuid import UUID
from datetime import date, time, datetime, timedelta
from typing import Optional

from app.models.patient import Patient
from app.models.appointment import Appointment
from app.models.appointment_type import AppointmentType
from app.models.schedule import ScheduleTemplate, ScheduleOverride
from app.models.practice_config import PracticeConfig
from app.models.holiday import Holiday


# ---------------------------------------------------------------------------
# 1. Patient lookup and creation
# ---------------------------------------------------------------------------

async def find_or_create_patient(
    db: AsyncSession,
    practice_id: UUID,
    first_name: str,
    last_name: str,
    dob: date,
    phone: Optional[str] = None,
    address: Optional[str] = None,
    insurance_carrier: Optional[str] = None,
    member_id: Optional[str] = None,
    group_number: Optional[str] = None,
    referring_physician: Optional[str] = None,
    accident_date: Optional[date] = None,
    accident_type: Optional[str] = None,
    language_preference: Optional[str] = None,
    notes: Optional[str] = None,
) -> Patient:
    """
    Search for an existing patient by (practice_id + first_name + last_name + dob)
    using case-insensitive matching. If found, update any newly provided fields and
    return the patient. If not found, create a new patient with is_new=True.
    """
    stmt = (
        select(Patient)
        .where(
            and_(
                Patient.practice_id == practice_id,
                func.lower(Patient.first_name) == first_name.lower(),
                func.lower(Patient.last_name) == last_name.lower(),
                Patient.dob == dob,
            )
        )
    )
    result = await db.execute(stmt)
    patient = result.scalar_one_or_none()

    if patient:
        # Update any newly provided optional fields
        updatable = {
            "phone": phone,
            "address": address,
            "insurance_carrier": insurance_carrier,
            "member_id": member_id,
            "group_number": group_number,
            "referring_physician": referring_physician,
            "accident_date": accident_date,
            "accident_type": accident_type,
            "language_preference": language_preference,
            "notes": notes,
        }
        changed = False
        for field, value in updatable.items():
            if value is not None and getattr(patient, field) != value:
                setattr(patient, field, value)
                changed = True

        if changed:
            await db.flush()
            await db.refresh(patient)

        return patient

    # Create new patient
    patient = Patient(
        practice_id=practice_id,
        first_name=first_name,
        last_name=last_name,
        dob=dob,
        phone=phone,
        address=address,
        insurance_carrier=insurance_carrier,
        member_id=member_id,
        group_number=group_number,
        referring_physician=referring_physician,
        accident_date=accident_date,
        accident_type=accident_type,
        is_new=True,
        language_preference=language_preference or "en",
        notes=notes,
    )
    db.add(patient)
    await db.flush()
    await db.refresh(patient)
    return patient


# ---------------------------------------------------------------------------
# 2. Patient search
# ---------------------------------------------------------------------------

async def search_patients(
    db: AsyncSession,
    practice_id: UUID,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    dob: Optional[date] = None,
    phone: Optional[str] = None,
) -> list[Patient]:
    """
    Search patients by any combination of fields (at least one required).
    Uses ILIKE for name fields. Practice-scoped. Limited to 20 results.
    """
    if not any([first_name, last_name, dob, phone]):
        raise ValueError("At least one search parameter is required")

    filters = [Patient.practice_id == practice_id]

    if first_name:
        filters.append(Patient.first_name.ilike(f"%{first_name}%"))
    if last_name:
        filters.append(Patient.last_name.ilike(f"%{last_name}%"))
    if dob:
        filters.append(Patient.dob == dob)
    if phone:
        filters.append(Patient.phone.ilike(f"%{phone}%"))

    stmt = select(Patient).where(and_(*filters)).limit(20)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# 3. Available slots
# ---------------------------------------------------------------------------

async def _get_practice_config(db: AsyncSession, practice_id: UUID) -> PracticeConfig:
    """Fetch the practice config, raising ValueError if not found."""
    stmt = select(PracticeConfig).where(PracticeConfig.practice_id == practice_id)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()
    if not config:
        raise ValueError(f"Practice config not found for practice {practice_id}")
    return config


async def _get_schedule_for_date(
    db: AsyncSession,
    practice_id: UUID,
    target_date: date,
) -> tuple[bool, Optional[time], Optional[time]]:
    """
    Determine whether a date is a working day and its start/end times.
    Checks overrides first, then falls back to the weekly template.
    Also checks the holidays table.

    Returns (is_working, start_time, end_time).
    """
    # Check for holiday
    holiday_stmt = select(Holiday).where(Holiday.date == target_date)
    holiday_result = await db.execute(holiday_stmt)
    if holiday_result.scalar_one_or_none():
        return (False, None, None)

    # Check for override on this specific date
    override_stmt = (
        select(ScheduleOverride)
        .where(
            and_(
                ScheduleOverride.practice_id == practice_id,
                ScheduleOverride.date == target_date,
            )
        )
    )
    override_result = await db.execute(override_stmt)
    override = override_result.scalar_one_or_none()

    if override:
        return (override.is_working, override.start_time, override.end_time)

    # Fall back to weekly schedule template (Monday=0 ... Sunday=6)
    day_of_week = target_date.weekday()
    template_stmt = (
        select(ScheduleTemplate)
        .where(
            and_(
                ScheduleTemplate.practice_id == practice_id,
                ScheduleTemplate.day_of_week == day_of_week,
            )
        )
    )
    template_result = await db.execute(template_stmt)
    template = template_result.scalar_one_or_none()

    if not template or not template.is_enabled:
        return (False, None, None)

    return (True, template.start_time, template.end_time)


def _generate_time_slots(
    start_time: time,
    end_time: time,
    slot_duration_minutes: int,
) -> list[time]:
    """Generate a list of time slot start times from start_time to end_time."""
    slots: list[time] = []
    current_dt = datetime.combine(date.today(), start_time)
    end_dt = datetime.combine(date.today(), end_time)

    while current_dt + timedelta(minutes=slot_duration_minutes) <= end_dt:
        slots.append(current_dt.time())
        current_dt += timedelta(minutes=slot_duration_minutes)

    return slots


async def get_available_slots(
    db: AsyncSession,
    practice_id: UUID,
    target_date: date,
    appointment_type_id: Optional[UUID] = None,
) -> list[dict]:
    """
    Return a list of time slot dicts for the given date.

    Each dict: {"time": time_obj, "is_available": bool, "current_bookings": int}

    Steps:
    1. Check schedule override / template for the date.
    2. Determine slot duration from appointment type or practice config.
    3. Generate time slots.
    4. Count existing non-cancelled appointments per slot.
    5. Apply overbooking rules from practice config.
    """
    is_working, start_time, end_time = await _get_schedule_for_date(
        db, practice_id, target_date
    )
    if not is_working or start_time is None or end_time is None:
        return []

    config = await _get_practice_config(db, practice_id)

    # Determine slot duration
    slot_duration = config.slot_duration_minutes
    if appointment_type_id:
        appt_type_stmt = (
            select(AppointmentType)
            .where(
                and_(
                    AppointmentType.id == appointment_type_id,
                    AppointmentType.practice_id == practice_id,
                )
            )
        )
        appt_type_result = await db.execute(appt_type_stmt)
        appt_type = appt_type_result.scalar_one_or_none()
        if appt_type:
            slot_duration = appt_type.duration_minutes

    time_slots = _generate_time_slots(start_time, end_time, slot_duration)
    if not time_slots:
        return []

    # Count existing non-cancelled appointments per time slot on this date
    bookings_stmt = (
        select(Appointment.time, func.count(Appointment.id))
        .where(
            and_(
                Appointment.practice_id == practice_id,
                Appointment.date == target_date,
                Appointment.status != "cancelled",
            )
        )
        .group_by(Appointment.time)
    )
    bookings_result = await db.execute(bookings_stmt)
    bookings_map: dict[time, int] = {
        row[0]: row[1] for row in bookings_result.all()
    }

    # Build slot availability list
    max_per_slot = 1
    if config.allow_overbooking:
        max_per_slot = config.max_overbooking_per_slot

    slots: list[dict] = []
    for t in time_slots:
        current_count = bookings_map.get(t, 0)
        slots.append(
            {
                "time": t,
                "is_available": current_count < max_per_slot,
                "current_bookings": current_count,
            }
        )

    return slots


# ---------------------------------------------------------------------------
# 4. Find next available slot
# ---------------------------------------------------------------------------

async def find_next_available_slot(
    db: AsyncSession,
    practice_id: UUID,
    appointment_type_id: Optional[UUID] = None,
    from_date: Optional[date] = None,
    preferred_time: Optional[time] = None,
) -> Optional[dict]:
    """
    Starting from from_date (default: today), search up to booking_horizon_days
    for the first available slot. If preferred_time is given, return the closest
    available slot to that time. Otherwise return the first available slot of the
    earliest available day.

    Returns {"date": date, "time": time} or None if nothing found.
    """
    config = await _get_practice_config(db, practice_id)
    start_date = from_date or date.today()
    horizon = config.booking_horizon_days

    for day_offset in range(horizon):
        check_date = start_date + timedelta(days=day_offset)
        slots = await get_available_slots(
            db, practice_id, check_date, appointment_type_id
        )
        available = [s for s in slots if s["is_available"]]
        if not available:
            continue

        if preferred_time:
            # Find the slot closest to the preferred time
            def time_distance(slot_dict: dict) -> int:
                slot_seconds = (
                    slot_dict["time"].hour * 3600
                    + slot_dict["time"].minute * 60
                    + slot_dict["time"].second
                )
                pref_seconds = (
                    preferred_time.hour * 3600
                    + preferred_time.minute * 60
                    + preferred_time.second
                )
                return abs(slot_seconds - pref_seconds)

            best = min(available, key=time_distance)
            return {"date": check_date, "time": best["time"]}
        else:
            return {"date": check_date, "time": available[0]["time"]}

    return None


# ---------------------------------------------------------------------------
# 5. Book appointment
# ---------------------------------------------------------------------------

async def book_appointment(
    db: AsyncSession,
    practice_id: UUID,
    patient_id: UUID,
    appointment_type_id: UUID,
    appt_date: date,
    appt_time: time,
    booked_by: str = "ai",
    call_id: Optional[UUID] = None,
    notes: Optional[str] = None,
) -> Appointment:
    """
    Create a new appointment after validating the type and slot availability.

    Raises ValueError if validation fails (wrong practice, inactive type,
    slot not available).
    """
    # Validate appointment type exists and belongs to this practice
    appt_type_stmt = (
        select(AppointmentType)
        .where(
            and_(
                AppointmentType.id == appointment_type_id,
                AppointmentType.practice_id == practice_id,
            )
        )
    )
    appt_type_result = await db.execute(appt_type_stmt)
    appt_type = appt_type_result.scalar_one_or_none()

    if not appt_type:
        raise ValueError(
            "Appointment type not found or does not belong to this practice"
        )

    if not appt_type.is_active:
        raise ValueError("Appointment type is not active")

    # Validate the slot is available
    slots = await get_available_slots(
        db, practice_id, appt_date, appointment_type_id
    )
    matching_slot = next((s for s in slots if s["time"] == appt_time), None)

    if not matching_slot:
        raise ValueError(
            f"Time slot {appt_time.strftime('%H:%M')} is not a valid slot "
            f"on {appt_date.isoformat()}"
        )

    if not matching_slot["is_available"]:
        raise ValueError(
            f"Time slot {appt_time.strftime('%H:%M')} on {appt_date.isoformat()} "
            f"is fully booked"
        )

    # Create the appointment
    appointment = Appointment(
        practice_id=practice_id,
        patient_id=patient_id,
        appointment_type_id=appointment_type_id,
        date=appt_date,
        time=appt_time,
        duration_minutes=appt_type.duration_minutes,
        status="booked",
        booked_by=booked_by,
        call_id=call_id,
        notes=notes,
    )
    db.add(appointment)
    await db.flush()
    await db.refresh(appointment)

    # If the patient was marked as new, flip the flag after first booking
    patient_stmt = select(Patient).where(
        and_(
            Patient.id == patient_id,
            Patient.practice_id == practice_id,
        )
    )
    patient_result = await db.execute(patient_stmt)
    patient = patient_result.scalar_one_or_none()

    if patient and patient.is_new:
        patient.is_new = False
        await db.flush()

    return appointment


# ---------------------------------------------------------------------------
# 6. Cancel appointment
# ---------------------------------------------------------------------------

async def cancel_appointment(
    db: AsyncSession,
    appointment_id: UUID,
    practice_id: UUID,
    reason: Optional[str] = None,
) -> Appointment:
    """
    Cancel an appointment. Sets status to 'cancelled' and optionally appends
    a cancellation reason to notes.

    Raises ValueError if not found or already cancelled.
    """
    stmt = (
        select(Appointment)
        .where(
            and_(
                Appointment.id == appointment_id,
                Appointment.practice_id == practice_id,
            )
        )
    )
    result = await db.execute(stmt)
    appointment = result.scalar_one_or_none()

    if not appointment:
        raise ValueError("Appointment not found")

    if appointment.status == "cancelled":
        raise ValueError("Appointment is already cancelled")

    appointment.status = "cancelled"

    # Append reason to existing notes
    if reason:
        cancellation_note = f"Cancelled: {reason}"
        if appointment.notes:
            appointment.notes = f"{appointment.notes}\n{cancellation_note}"
        else:
            appointment.notes = cancellation_note

    await db.flush()
    await db.refresh(appointment)
    return appointment


# ---------------------------------------------------------------------------
# 7. Reschedule appointment
# ---------------------------------------------------------------------------

async def reschedule_appointment(
    db: AsyncSession,
    appointment_id: UUID,
    practice_id: UUID,
    new_date: date,
    new_time: time,
    notes: Optional[str] = None,
) -> Appointment:
    """
    Reschedule an existing appointment to a new date/time.

    Cancels the old appointment (with 'Rescheduled' note) and creates a new one
    carrying over the patient, appointment type, and booked_by fields.

    Raises ValueError if the old appointment is not found or the new slot is
    not available.
    """
    # Find the existing appointment
    stmt = (
        select(Appointment)
        .where(
            and_(
                Appointment.id == appointment_id,
                Appointment.practice_id == practice_id,
            )
        )
    )
    result = await db.execute(stmt)
    old_appointment = result.scalar_one_or_none()

    if not old_appointment:
        raise ValueError("Appointment not found")

    if old_appointment.status == "cancelled":
        raise ValueError("Cannot reschedule a cancelled appointment")

    # Validate the new slot is available
    slots = await get_available_slots(
        db, practice_id, new_date, old_appointment.appointment_type_id
    )
    matching_slot = next((s for s in slots if s["time"] == new_time), None)

    if not matching_slot:
        raise ValueError(
            f"Time slot {new_time.strftime('%H:%M')} is not a valid slot "
            f"on {new_date.isoformat()}"
        )

    if not matching_slot["is_available"]:
        raise ValueError(
            f"Time slot {new_time.strftime('%H:%M')} on {new_date.isoformat()} "
            f"is fully booked"
        )

    # Cancel the old appointment with a reschedule note
    reschedule_note = f"Rescheduled to {new_date.isoformat()} {new_time.strftime('%H:%M')}"
    old_appointment.status = "cancelled"
    if old_appointment.notes:
        old_appointment.notes = f"{old_appointment.notes}\n{reschedule_note}"
    else:
        old_appointment.notes = reschedule_note

    # Create the new appointment
    new_appointment = Appointment(
        practice_id=practice_id,
        patient_id=old_appointment.patient_id,
        appointment_type_id=old_appointment.appointment_type_id,
        date=new_date,
        time=new_time,
        duration_minutes=old_appointment.duration_minutes,
        status="booked",
        booked_by=old_appointment.booked_by,
        call_id=old_appointment.call_id,
        notes=notes,
    )
    db.add(new_appointment)
    await db.flush()
    await db.refresh(new_appointment)

    return new_appointment


# ---------------------------------------------------------------------------
# 8. Confirm appointment
# ---------------------------------------------------------------------------

async def confirm_appointment(
    db: AsyncSession,
    appointment_id: UUID,
    practice_id: UUID,
) -> Appointment:
    """
    Confirm a booked appointment by setting its status to 'confirmed'.

    Raises ValueError if the appointment is not found or not in 'booked' status.
    """
    stmt = (
        select(Appointment)
        .where(
            and_(
                Appointment.id == appointment_id,
                Appointment.practice_id == practice_id,
            )
        )
    )
    result = await db.execute(stmt)
    appointment = result.scalar_one_or_none()

    if not appointment:
        raise ValueError("Appointment not found")

    if appointment.status != "booked":
        raise ValueError(
            f"Cannot confirm appointment with status '{appointment.status}'. "
            f"Only appointments with status 'booked' can be confirmed."
        )

    appointment.status = "confirmed"
    await db.flush()
    await db.refresh(appointment)
    return appointment


# ---------------------------------------------------------------------------
# 9. Get appointments (list with filters)
# ---------------------------------------------------------------------------

async def get_appointments(
    db: AsyncSession,
    practice_id: UUID,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    patient_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Appointment], int]:
    """
    Query appointments with optional filters. Returns a tuple of
    (appointment_list, total_count) for pagination support.

    Results are ordered by date ascending, then time ascending.
    """
    filters = [Appointment.practice_id == practice_id]

    if from_date:
        filters.append(Appointment.date >= from_date)
    if to_date:
        filters.append(Appointment.date <= to_date)
    if patient_id:
        filters.append(Appointment.patient_id == patient_id)
    if status_filter:
        filters.append(Appointment.status == status_filter)

    where_clause = and_(*filters)

    # Total count query
    count_stmt = select(func.count(Appointment.id)).where(where_clause)
    count_result = await db.execute(count_stmt)
    total_count = count_result.scalar_one()

    # Data query with ordering and pagination
    data_stmt = (
        select(Appointment)
        .where(where_clause)
        .order_by(Appointment.date, Appointment.time)
        .limit(limit)
        .offset(offset)
    )
    data_result = await db.execute(data_stmt)
    appointments = list(data_result.scalars().all())

    return (appointments, total_count)
