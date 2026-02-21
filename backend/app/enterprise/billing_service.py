"""
Per-practice billing & usage metering.

Tracks usage events (calls, SMS, insurance checks, etc.) and calculates
monthly bills based on pricing tiers with overage charges.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pricing tiers
# ---------------------------------------------------------------------------

PLANS = {
    "starter": {
        "name": "Starter",
        "base_price": Decimal("799.00"),
        "limits": {"call_handled": 500, "sms_sent": 1000, "insurance_check": 200},
        "overage": {"call_handled": Decimal("0.50"), "sms_sent": Decimal("0.05"), "insurance_check": Decimal("0.25")},
    },
    "professional": {
        "name": "Professional",
        "base_price": Decimal("1499.00"),
        "limits": {"call_handled": 2000, "sms_sent": 5000, "insurance_check": 1000},
        "overage": {"call_handled": Decimal("0.40"), "sms_sent": Decimal("0.04"), "insurance_check": Decimal("0.20")},
    },
    "enterprise": {
        "name": "Enterprise",
        "base_price": Decimal("2999.00"),
        "limits": {"call_handled": 999999, "sms_sent": 999999, "insurance_check": 999999},
        "overage": {"call_handled": Decimal("0"), "sms_sent": Decimal("0"), "insurance_check": Decimal("0")},
    },
}

VALID_USAGE_TYPES = {"call_handled", "sms_sent", "insurance_check", "ehr_sync", "survey_sent"}


class UsageSummary(BaseModel):
    month: str
    calls: int = 0
    sms: int = 0
    insurance_checks: int = 0
    ehr_syncs: int = 0
    surveys: int = 0
    total_cost: float = 0


class MonthlyBill(BaseModel):
    month: str
    plan_name: str
    base_amount: float
    overage_amount: float
    total_amount: float
    status: str = "pending"
    usage: dict = {}


# ---------------------------------------------------------------------------
# BillingService
# ---------------------------------------------------------------------------

class BillingService:

    @staticmethod
    async def record_usage(
        db: AsyncSession,
        practice_id: str,
        usage_type: str,
        quantity: int = 1,
        metadata: Optional[dict] = None,
    ) -> None:
        """Record a usage event."""
        if usage_type not in VALID_USAGE_TYPES:
            logger.warning("Invalid usage type: %s", usage_type)
            return

        import json
        await db.execute(
            text("""
                INSERT INTO usage_events (id, practice_id, usage_type, quantity, metadata, created_at)
                VALUES (gen_random_uuid(), :pid, :type, :qty, :meta::jsonb, NOW())
            """),
            {
                "pid": practice_id,
                "type": usage_type,
                "qty": quantity,
                "meta": json.dumps(metadata) if metadata else "{}",
            },
        )
        await db.commit()

    @staticmethod
    async def get_usage_summary(
        db: AsyncSession, practice_id: str, month: str
    ) -> UsageSummary:
        """Get usage summary for a specific month (format: YYYY-MM)."""
        result = await db.execute(
            text("""
                SELECT usage_type, COALESCE(SUM(quantity), 0) AS total
                FROM usage_events
                WHERE practice_id = :pid
                  AND TO_CHAR(created_at, 'YYYY-MM') = :month
                GROUP BY usage_type
            """),
            {"pid": practice_id, "month": month},
        )

        usage = {}
        for row in result.fetchall():
            usage[row.usage_type] = int(row.total)

        return UsageSummary(
            month=month,
            calls=usage.get("call_handled", 0),
            sms=usage.get("sms_sent", 0),
            insurance_checks=usage.get("insurance_check", 0),
            ehr_syncs=usage.get("ehr_sync", 0),
            surveys=usage.get("survey_sent", 0),
        )

    @staticmethod
    async def calculate_monthly_bill(
        db: AsyncSession, practice_id: str, month: str
    ) -> MonthlyBill:
        """Calculate the monthly bill including overages."""
        # Get practice plan
        plan_result = await db.execute(
            text("SELECT config FROM practices WHERE id = :pid"),
            {"pid": practice_id},
        )
        plan_row = plan_result.fetchone()
        plan_name = "starter"
        if plan_row and plan_row.config:
            config = plan_row.config if isinstance(plan_row.config, dict) else {}
            plan_name = config.get("billing_plan", "starter")

        plan = PLANS.get(plan_name, PLANS["starter"])
        summary = await BillingService.get_usage_summary(db, practice_id, month)

        # Calculate overages
        overage = Decimal("0")
        usage_detail = {
            "call_handled": summary.calls,
            "sms_sent": summary.sms,
            "insurance_check": summary.insurance_checks,
        }

        for usage_type, count in usage_detail.items():
            limit = plan["limits"].get(usage_type, 0)
            if count > limit:
                excess = count - limit
                rate = plan["overage"].get(usage_type, Decimal("0"))
                overage += rate * excess

        total = plan["base_price"] + overage

        return MonthlyBill(
            month=month,
            plan_name=plan["name"],
            base_amount=float(plan["base_price"]),
            overage_amount=float(overage),
            total_amount=float(total),
            usage=usage_detail,
        )

    @staticmethod
    async def get_billing_history(
        db: AsyncSession, practice_id: str, months: int = 12
    ) -> list[dict]:
        """Get billing history for a practice."""
        result = await db.execute(
            text("""
                SELECT id, month, plan_name, base_amount, overage_amount,
                       total_amount, status, created_at, paid_at
                FROM monthly_bills
                WHERE practice_id = :pid
                ORDER BY month DESC
                LIMIT :limit
            """),
            {"pid": practice_id, "limit": months},
        )
        return [
            {
                "id": str(row.id),
                "month": row.month,
                "plan_name": row.plan_name,
                "base_amount": float(row.base_amount),
                "overage_amount": float(row.overage_amount),
                "total_amount": float(row.total_amount),
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "paid_at": row.paid_at.isoformat() if row.paid_at else None,
            }
            for row in result.fetchall()
        ]

    @staticmethod
    async def generate_invoice(
        db: AsyncSession, practice_id: str, month: str
    ) -> dict:
        """Generate/retrieve an invoice for a month."""
        # Check if bill already exists
        existing = await db.execute(
            text("""
                SELECT id, total_amount, status FROM monthly_bills
                WHERE practice_id = :pid AND month = :month
            """),
            {"pid": practice_id, "month": month},
        )
        row = existing.fetchone()
        if row:
            return {
                "invoice_id": str(row.id),
                "total_amount": float(row.total_amount),
                "status": row.status,
                "already_exists": True,
            }

        # Calculate and insert
        bill = await BillingService.calculate_monthly_bill(db, practice_id, month)

        result = await db.execute(
            text("""
                INSERT INTO monthly_bills
                    (id, practice_id, month, plan_name, base_amount,
                     overage_amount, total_amount, status, created_at)
                VALUES
                    (gen_random_uuid(), :pid, :month, :plan, :base,
                     :overage, :total, 'pending', NOW())
                RETURNING id
            """),
            {
                "pid": practice_id,
                "month": month,
                "plan": bill.plan_name,
                "base": bill.base_amount,
                "overage": bill.overage_amount,
                "total": bill.total_amount,
            },
        )
        invoice_row = result.fetchone()
        await db.commit()

        return {
            "invoice_id": str(invoice_row.id),
            "month": month,
            "plan_name": bill.plan_name,
            "base_amount": bill.base_amount,
            "overage_amount": bill.overage_amount,
            "total_amount": bill.total_amount,
            "usage": bill.usage,
            "status": "pending",
        }
