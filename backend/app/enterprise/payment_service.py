"""
Stripe payment collection — copays and outstanding balances during calls.

Sends payment links via SMS and processes Stripe webhooks.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

logger = logging.getLogger(__name__)


class StripePaymentService:
    """Handle payment collection via Stripe."""

    @staticmethod
    async def create_payment_link(
        db: AsyncSession,
        practice_id: str,
        patient_phone: str,
        amount_cents: int,
        description: str,
        patient_id: Optional[str] = None,
    ) -> dict:
        """Create a Stripe Checkout session and send payment link via SMS."""
        settings = get_settings()

        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY

            # Create checkout session
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[
                    {
                        "price_data": {
                            "currency": "usd",
                            "unit_amount": amount_cents,
                            "product_data": {"name": description},
                        },
                        "quantity": 1,
                    }
                ],
                mode="payment",
                success_url=f"{settings.APP_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{settings.APP_URL}/payment/cancelled",
                metadata={
                    "practice_id": practice_id,
                    "patient_phone": patient_phone,
                    "patient_id": patient_id or "",
                },
                expires_after_completion={"enabled": True, "after": 300},
            )

            # Record payment in DB
            await db.execute(
                text("""
                    INSERT INTO payments
                        (id, practice_id, patient_id, patient_phone, amount_cents,
                         description, stripe_checkout_session_id, status, created_at)
                    VALUES
                        (gen_random_uuid(), :pid, :patient_id, :phone, :amount,
                         :desc, :session_id, 'pending', NOW())
                """),
                {
                    "pid": practice_id,
                    "patient_id": patient_id,
                    "phone": patient_phone,
                    "amount": amount_cents,
                    "desc": description[:500],
                    "session_id": session.id,
                },
            )
            await db.commit()

            # Send SMS with payment link
            amount_dollars = amount_cents / 100
            message = (
                f"You have a ${amount_dollars:.2f} payment due for {description}. "
                f"Pay securely: {session.url}"
            )
            await _send_payment_sms(patient_phone, message, practice_id)

            return {
                "checkout_url": session.url,
                "session_id": session.id,
                "amount_cents": amount_cents,
                "status": "pending",
            }

        except Exception as e:
            logger.error("Payment link creation failed: %s", e)
            raise

    @staticmethod
    async def check_payment_status(
        db: AsyncSession, session_id: str
    ) -> dict:
        """Check payment status by Stripe session ID."""
        result = await db.execute(
            text("""
                SELECT id, amount_cents, status, paid_at, created_at
                FROM payments
                WHERE stripe_checkout_session_id = :sid
            """),
            {"sid": session_id},
        )
        row = result.fetchone()
        if not row:
            return {"error": "Payment not found"}

        return {
            "payment_id": str(row.id),
            "amount_cents": row.amount_cents,
            "status": row.status,
            "paid_at": row.paid_at.isoformat() if row.paid_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    async def process_webhook(
        db: AsyncSession, payload: bytes, sig_header: str
    ) -> dict:
        """Process Stripe webhook events."""
        settings = get_settings()

        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY

            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except Exception as e:
            logger.error("Stripe webhook verification failed: %s", e)
            raise ValueError(f"Webhook verification failed: {e}")

        event_type = event["type"]
        data = event["data"]["object"]

        if event_type == "checkout.session.completed":
            session_id = data["id"]
            payment_intent = data.get("payment_intent", "")

            await db.execute(
                text("""
                    UPDATE payments SET
                        status = 'paid',
                        stripe_payment_intent_id = :pi_id,
                        paid_at = NOW()
                    WHERE stripe_checkout_session_id = :sid
                """),
                {"pi_id": payment_intent, "sid": session_id},
            )
            await db.commit()

            # Send confirmation SMS
            result = await db.execute(
                text("""
                    SELECT patient_phone, amount_cents, practice_id
                    FROM payments WHERE stripe_checkout_session_id = :sid
                """),
                {"sid": session_id},
            )
            row = result.fetchone()
            if row:
                amount = row.amount_cents / 100
                await _send_payment_sms(
                    row.patient_phone,
                    f"Payment of ${amount:.2f} received. Thank you!",
                    str(row.practice_id),
                )

            return {"status": "paid", "session_id": session_id}

        elif event_type == "payment_intent.payment_failed":
            pi_id = data["id"]
            await db.execute(
                text("""
                    UPDATE payments SET status = 'failed'
                    WHERE stripe_payment_intent_id = :pi_id
                """),
                {"pi_id": pi_id},
            )
            await db.commit()
            return {"status": "failed", "payment_intent_id": pi_id}

        return {"status": "ignored", "event_type": event_type}

    @staticmethod
    async def get_payment_history(
        db: AsyncSession,
        practice_id: str,
        patient_phone: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get payment history with optional phone filter."""
        query = """
            SELECT id, patient_phone, amount_cents, description,
                   status, created_at, paid_at
            FROM payments
            WHERE practice_id = :pid
        """
        params: dict = {"pid": practice_id, "limit": limit}

        if patient_phone:
            query += " AND patient_phone = :phone"
            params["phone"] = patient_phone

        query += " ORDER BY created_at DESC LIMIT :limit"

        result = await db.execute(text(query), params)
        return [
            {
                "id": str(row.id),
                "patient_phone": row.patient_phone,
                "amount_cents": row.amount_cents,
                "amount_dollars": round(row.amount_cents / 100, 2),
                "description": row.description,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "paid_at": row.paid_at.isoformat() if row.paid_at else None,
            }
            for row in result.fetchall()
        ]

    @staticmethod
    async def get_payment_stats(
        db: AsyncSession, practice_id: str
    ) -> dict:
        """Get payment collection statistics."""
        result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(CASE WHEN status = 'paid' THEN 1 END) AS paid_count,
                    COUNT(CASE WHEN status = 'pending' THEN 1 END) AS pending_count,
                    COALESCE(SUM(CASE WHEN status = 'paid' THEN amount_cents END), 0) AS total_collected,
                    COALESCE(SUM(CASE WHEN status = 'pending' THEN amount_cents END), 0) AS total_pending,
                    AVG(CASE WHEN status = 'paid' THEN
                        EXTRACT(EPOCH FROM (paid_at - created_at)) / 3600
                    END) AS avg_hours_to_pay
                FROM payments
                WHERE practice_id = :pid
                  AND created_at >= NOW() - INTERVAL '30 days'
            """),
            {"pid": practice_id},
        )
        row = result.fetchone()

        return {
            "total_payments": row.total or 0,
            "paid_count": row.paid_count or 0,
            "pending_count": row.pending_count or 0,
            "total_collected_cents": int(row.total_collected or 0),
            "total_collected_dollars": round(int(row.total_collected or 0) / 100, 2),
            "total_pending_cents": int(row.total_pending or 0),
            "avg_hours_to_pay": round(float(row.avg_hours_to_pay or 0), 1),
            "collection_rate_pct": (
                round((row.paid_count or 0) / row.total * 100, 1)
                if row.total > 0
                else 0
            ),
        }


async def _send_payment_sms(phone: str, message: str, practice_id: str) -> bool:
    settings = get_settings()
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        logger.warning("Twilio not configured — payment SMS not sent")
        return False
    try:
        from twilio.rest import Client
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.messages.create(body=message, from_=settings.TWILIO_ACCOUNT_SID, to=phone)
        return True
    except Exception as e:
        logger.error("Payment SMS failed to %s: %s", phone, e)
        return False
