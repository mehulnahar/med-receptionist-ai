"""SMS notification endpoints — send confirmations and custom messages."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.appointment import Appointment
from app.schemas.sms import SendSmsRequest, SendConfirmationRequest, SmsResponse
from app.middleware.auth import get_current_user, require_any_staff
from app.services.sms_service import send_appointment_confirmation, send_custom_sms

router = APIRouter()


def _ensure_practice(user: User) -> UUID:
    """Return the user's practice_id or raise 400 if it is None."""
    if not user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )
    return user.practice_id


async def _verify_appointment_ownership(
    db: AsyncSession, appointment_id: UUID, practice_id: UUID
) -> Appointment:
    """Fetch appointment and verify it belongs to the given practice."""
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
            detail="Appointment not found or does not belong to your practice",
        )
    return appt


# ---------------------------------------------------------------------------
# Send appointment confirmation SMS (body request)
# ---------------------------------------------------------------------------


@router.post("/send-confirmation", response_model=SmsResponse)
async def send_confirmation(
    request: SendConfirmationRequest,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Send an appointment confirmation SMS using appointment_id from the request body."""
    practice_id = _ensure_practice(current_user)
    await _verify_appointment_ownership(db, request.appointment_id, practice_id)

    try:
        result = await send_appointment_confirmation(
            db=db,
            practice_id=practice_id,
            appointment_id=request.appointment_id,
        )
        return SmsResponse(**result)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        return SmsResponse(
            success=False,
            error=f"Failed to send confirmation SMS: {str(exc)}",
        )


# ---------------------------------------------------------------------------
# Send custom SMS
# ---------------------------------------------------------------------------


@router.post("/send", response_model=SmsResponse)
async def send_custom(
    request: SendSmsRequest,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Send a custom SMS to any phone number."""
    practice_id = _ensure_practice(current_user)

    try:
        result = await send_custom_sms(
            db=db,
            practice_id=practice_id,
            to_number=request.to_number,
            body=request.body,
        )
        return SmsResponse(**result)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        return SmsResponse(
            success=False,
            error=f"Failed to send SMS: {str(exc)}",
        )


# ---------------------------------------------------------------------------
# Send appointment confirmation SMS (path param — more RESTful)
# ---------------------------------------------------------------------------


@router.post("/send-confirmation/{appointment_id}", response_model=SmsResponse)
async def send_confirmation_by_path(
    appointment_id: UUID,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Send an appointment confirmation SMS using appointment_id from the URL path."""
    practice_id = _ensure_practice(current_user)
    await _verify_appointment_ownership(db, appointment_id, practice_id)

    try:
        result = await send_appointment_confirmation(
            db=db,
            practice_id=practice_id,
            appointment_id=appointment_id,
        )
        return SmsResponse(**result)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        return SmsResponse(
            success=False,
            error=f"Failed to send confirmation SMS: {str(exc)}",
        )
