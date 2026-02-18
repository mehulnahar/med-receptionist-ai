"""
Call logging service for the AI Medical Receptionist.

Provides async functions for creating, updating, and querying call records.
Called from the Vapi webhook handler to persist call lifecycle events:
- Call creation on assistant-request or first status-update
- Status updates as the call progresses
- End-of-call report with transcript, recording, summary, cost
- Linking calls to patients and appointments

All functions use flush/refresh (NOT commit) so the caller controls
transaction boundaries.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from uuid import UUID
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.models.call import Call
from app.models.practice_config import PracticeConfig


# ---------------------------------------------------------------------------
# 1. Create or update a call record
# ---------------------------------------------------------------------------

async def create_or_update_call(
    db: AsyncSession,
    practice_id: UUID,
    vapi_call_id: str,
    **kwargs: Any,
) -> Call:
    """
    Find an existing call by vapi_call_id and update it, or create a new one.

    Any additional keyword arguments are set as attributes on the Call model
    (e.g. caller_phone, direction, language, status, started_at).

    Returns the created or updated Call instance.
    """
    stmt = select(Call).where(Call.vapi_call_id == vapi_call_id)
    result = await db.execute(stmt)
    call = result.scalar_one_or_none()

    if call:
        # Update existing call with any provided fields
        for field, value in kwargs.items():
            if value is not None and hasattr(call, field):
                setattr(call, field, value)
        await db.flush()
        await db.refresh(call)
        return call

    # Create new call record
    call = Call(
        practice_id=practice_id,
        vapi_call_id=vapi_call_id,
        **{k: v for k, v in kwargs.items() if v is not None and hasattr(Call, k)},
    )
    db.add(call)
    await db.flush()
    await db.refresh(call)
    return call


# ---------------------------------------------------------------------------
# 2. Update call status
# ---------------------------------------------------------------------------

async def update_call_status(
    db: AsyncSession,
    vapi_call_id: str,
    status: str,
    **kwargs: Any,
) -> Call | None:
    """
    Find a call by vapi_call_id and update its status.

    Additional kwargs are applied as field updates (e.g. started_at, ended_at).
    Returns the updated Call or None if no matching call was found.
    """
    stmt = select(Call).where(Call.vapi_call_id == vapi_call_id)
    result = await db.execute(stmt)
    call = result.scalar_one_or_none()

    if not call:
        return None

    call.status = status

    for field, value in kwargs.items():
        if value is not None and hasattr(call, field):
            setattr(call, field, value)

    await db.flush()
    await db.refresh(call)
    return call


# ---------------------------------------------------------------------------
# 3. Save end-of-call report
# ---------------------------------------------------------------------------

async def save_end_of_call_report(
    db: AsyncSession,
    vapi_call_id: str,
    transcript: str | None = None,
    recording_url: str | None = None,
    summary: str | None = None,
    duration: int | None = None,
    cost: float | None = None,
    ended_reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Call | None:
    """
    Save all end-of-call data to the call record.

    If duration is not explicitly provided but started_at and ended_at are
    available on the call record, the duration is calculated automatically.

    Returns the updated Call or None if no matching call was found.
    """
    stmt = select(Call).where(Call.vapi_call_id == vapi_call_id)
    result = await db.execute(stmt)
    call = result.scalar_one_or_none()

    if not call:
        return None

    if transcript is not None:
        call.transcription = transcript
    if recording_url is not None:
        call.recording_url = recording_url
    if summary is not None:
        call.ai_summary = summary
    if cost is not None:
        call.vapi_cost = Decimal(str(cost))
    if ended_reason is not None:
        call.status = "ended"
        call.outcome = ended_reason
    if metadata is not None:
        call.call_metadata = metadata

    # Set duration: use explicit value or calculate from timestamps
    if duration is not None:
        call.duration_seconds = duration
    elif call.duration_seconds is None and call.started_at and call.ended_at:
        delta = call.ended_at - call.started_at
        call.duration_seconds = int(delta.total_seconds())

    await db.flush()
    await db.refresh(call)
    return call


# ---------------------------------------------------------------------------
# 4. Link call to patient
# ---------------------------------------------------------------------------

async def link_call_to_patient(
    db: AsyncSession,
    vapi_call_id: str,
    patient_id: UUID,
) -> Call | None:
    """
    Update the patient_id on a call record.

    Returns the updated Call or None if no matching call was found.
    """
    stmt = select(Call).where(Call.vapi_call_id == vapi_call_id)
    result = await db.execute(stmt)
    call = result.scalar_one_or_none()

    if not call:
        return None

    call.patient_id = patient_id
    await db.flush()
    await db.refresh(call)
    return call


# ---------------------------------------------------------------------------
# 5. Link call to appointment
# ---------------------------------------------------------------------------

async def link_call_to_appointment(
    db: AsyncSession,
    vapi_call_id: str,
    appointment_id: UUID,
) -> Call | None:
    """
    Update the appointment_id on a call record.

    Returns the updated Call or None if no matching call was found.
    """
    stmt = select(Call).where(Call.vapi_call_id == vapi_call_id)
    result = await db.execute(stmt)
    call = result.scalar_one_or_none()

    if not call:
        return None

    call.appointment_id = appointment_id
    await db.flush()
    await db.refresh(call)
    return call


# ---------------------------------------------------------------------------
# 6. Get practice_id from a Vapi call
# ---------------------------------------------------------------------------

async def get_practice_id_from_vapi_call(
    db: AsyncSession,
    vapi_call_id: str,
) -> UUID | None:
    """
    Find the call record by vapi_call_id and return its practice_id.

    Returns None if no matching call was found.
    """
    stmt = select(Call.practice_id).where(Call.vapi_call_id == vapi_call_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return row


# ---------------------------------------------------------------------------
# 7. Resolve practice from Twilio phone number
# ---------------------------------------------------------------------------

async def save_caller_info_to_call(
    db: AsyncSession,
    vapi_call_id: str,
    caller_name: str | None = None,
    caller_phone: str | None = None,
    patient_id: UUID | None = None,
) -> Call | None:
    """
    Save early caller information (name, phone, patient link) to a call record.

    This is called mid-call by the save_caller_info tool so that even if the
    call drops, we already have the caller's identity on record for callbacks.

    Returns the updated Call or None if no matching call was found.
    """
    stmt = select(Call).where(Call.vapi_call_id == vapi_call_id)
    result = await db.execute(stmt)
    call = result.scalar_one_or_none()

    if not call:
        return None

    if caller_name is not None:
        call.caller_name = caller_name
    if caller_phone is not None and caller_phone.strip():
        call.caller_phone = caller_phone
    if patient_id is not None:
        call.patient_id = patient_id

    await db.flush()
    await db.refresh(call)
    return call


async def resolve_practice_from_phone(
    db: AsyncSession,
    phone_number: str,
) -> UUID | None:
    """
    Look up which practice a Twilio phone number belongs to by querying the
    practice_configs table for a matching twilio_phone_number.

    Returns the practice_id or None if no match is found.
    """
    stmt = (
        select(PracticeConfig.practice_id)
        .where(PracticeConfig.twilio_phone_number == phone_number)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return row
