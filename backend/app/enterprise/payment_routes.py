"""
Payment collection API routes — Stripe integration.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import require_any_staff, require_practice_admin
from app.models.user import User
from app.enterprise.payment_service import StripePaymentService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payments", tags=["Payments"])


class SendPaymentLinkRequest(BaseModel):
    patient_phone: str = Field(..., min_length=1, max_length=20)
    amount_cents: int = Field(..., gt=0, le=99999999)  # Max $999,999.99
    description: str = Field(..., min_length=1, max_length=500)
    patient_id: str | None = None


@router.post("/send-link")
async def send_payment_link(
    body: SendPaymentLinkRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_staff),
):
    """Send a payment link to a patient via SMS."""
    if not current_user.practice_id:
        raise HTTPException(status_code=400, detail="No practice associated")

    try:
        return await StripePaymentService.create_payment_link(
            db=db,
            practice_id=str(current_user.practice_id),
            patient_phone=body.patient_phone,
            amount_cents=body.amount_cents,
            description=body.description,
            patient_id=body.patient_id,
        )
    except Exception as e:
        logger.error("Payment link failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create payment link")


@router.get("/status/{session_id}")
async def payment_status(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_staff),
):
    """Check payment status."""
    result = await StripePaymentService.check_payment_status(db, session_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Stripe webhook handler — no auth, verified by signature."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        result = await StripePaymentService.process_webhook(db, payload, sig_header)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/history")
async def payment_history(
    patient_phone: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Get payment history."""
    if not current_user.practice_id:
        return {"payments": []}

    payments = await StripePaymentService.get_payment_history(
        db, str(current_user.practice_id), patient_phone, limit
    )
    return {"payments": payments}


@router.get("/stats")
async def payment_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Get payment collection statistics."""
    if not current_user.practice_id:
        return {"error": "No practice associated"}

    return await StripePaymentService.get_payment_stats(
        db, str(current_user.practice_id)
    )
