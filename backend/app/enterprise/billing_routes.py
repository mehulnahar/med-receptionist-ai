"""
Billing & usage metering API routes.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_practice_admin
from app.models.user import User
from app.enterprise.billing_service import BillingService, PLANS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["Billing"])


def _require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin required")
    return current_user


@router.get("/usage")
async def current_usage(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Get current month usage summary."""
    if not current_user.practice_id:
        raise HTTPException(status_code=400, detail="No practice associated")

    month = datetime.now(timezone.utc).strftime("%Y-%m")
    summary = await BillingService.get_usage_summary(
        db, str(current_user.practice_id), month
    )
    return summary.model_dump()


@router.get("/usage/{month}")
async def month_usage(
    month: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Get usage for a specific month (YYYY-MM)."""
    if not current_user.practice_id:
        raise HTTPException(status_code=400, detail="No practice associated")

    # Validate month format
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM")

    summary = await BillingService.get_usage_summary(
        db, str(current_user.practice_id), month
    )
    return summary.model_dump()


@router.get("/history")
async def billing_history(
    months: int = Query(12, ge=1, le=36),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Get billing history."""
    if not current_user.practice_id:
        return {"bills": []}

    bills = await BillingService.get_billing_history(
        db, str(current_user.practice_id), months
    )
    return {"bills": bills}


@router.get("/invoice/{month}")
async def get_invoice(
    month: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Get or generate invoice for a month."""
    if not current_user.practice_id:
        raise HTTPException(status_code=400, detail="No practice associated")

    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM")

    return await BillingService.generate_invoice(
        db, str(current_user.practice_id), month
    )


@router.get("/plans")
async def list_plans():
    """List available plans with pricing."""
    plans_list = []
    for key, plan in PLANS.items():
        plans_list.append({
            "id": key,
            "name": plan["name"],
            "base_price": float(plan["base_price"]),
            "limits": plan["limits"],
            "overage_rates": {k: float(v) for k, v in plan["overage"].items()},
        })
    return {"plans": plans_list}


@router.get("/admin/all-usage")
async def admin_all_usage(
    month: str = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_super_admin),
):
    """Get usage across all practices (super admin)."""
    if not month:
        month = datetime.now(timezone.utc).strftime("%Y-%m")

    result = await db.execute(
        text("""
            SELECT ue.practice_id, p.name AS practice_name,
                   ue.usage_type, COALESCE(SUM(ue.quantity), 0) AS total
            FROM usage_events ue
            JOIN practices p ON ue.practice_id = p.id
            WHERE TO_CHAR(ue.created_at, 'YYYY-MM') = :month
            GROUP BY ue.practice_id, p.name, ue.usage_type
            ORDER BY p.name, ue.usage_type
        """),
        {"month": month},
    )

    # Pivot into per-practice summaries
    practices = {}
    for row in result.fetchall():
        pid = str(row.practice_id)
        if pid not in practices:
            practices[pid] = {
                "practice_id": pid,
                "practice_name": row.practice_name,
                "usage": {},
            }
        practices[pid]["usage"][row.usage_type] = int(row.total)

    return {"month": month, "practices": list(practices.values())}


@router.post("/admin/generate-invoices")
async def admin_generate_invoices(
    month: str = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_super_admin),
):
    """Batch generate monthly invoices for all practices (super admin)."""
    if not month:
        month = datetime.now(timezone.utc).strftime("%Y-%m")

    # Get all active practices
    result = await db.execute(
        text("SELECT id FROM practices WHERE is_active = TRUE")
    )

    generated = 0
    errors = 0
    for row in result.fetchall():
        try:
            await BillingService.generate_invoice(db, str(row.id), month)
            generated += 1
        except Exception as e:
            logger.error("Invoice generation failed for %s: %s", row.id, e)
            errors += 1

    return {"month": month, "generated": generated, "errors": errors}
