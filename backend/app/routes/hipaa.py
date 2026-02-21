"""
HIPAA compliance API routes — audit logs, password management, session.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_super_admin, require_practice_admin
from app.models.user import User
from app.hipaa.password_policy import (
    validate_password_strength,
    calculate_password_strength,
    check_password_history,
    save_password_to_history,
    admin_unlock_account,
)
from app.hipaa.session_management import check_session_valid, record_session_activity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hipaa", tags=["HIPAA Compliance"])


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class PasswordStrengthRequest(BaseModel):
    password: str


@router.get("/audit-log")
async def get_audit_log(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    patient_id: str = Query(None),
    user_id: str = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """View PHI read access audit log. HIPAA requirement."""
    practice_id = str(current_user.practice_id) if current_user.practice_id else None

    # Build WHERE clause safely — column names are hardcoded, values use bind params
    filters = []
    params: dict = {"limit": limit, "offset": offset}

    if practice_id:
        filters.append("practice_id = :practice_id")
        params["practice_id"] = practice_id
    if patient_id:
        filters.append("patient_id = :patient_id")
        params["patient_id"] = patient_id
    if user_id:
        filters.append("user_id = :user_id")
        params["user_id"] = user_id

    where_clause = ("WHERE " + " AND ".join(filters)) if filters else ""

    result = await db.execute(text(
        "SELECT id, user_id, user_role, patient_id, endpoint, "
        "       ip_address, request_id, accessed_at "
        "FROM audit_read_logs "
        + where_clause + " "
        "ORDER BY accessed_at DESC "
        "LIMIT :limit OFFSET :offset"
    ), params)

    count_result = await db.execute(text(
        "SELECT COUNT(*) FROM audit_read_logs " + where_clause
    ), params)

    rows = result.fetchall()
    total = count_result.scalar()

    return {
        "total": total,
        "logs": [
            {
                "id": str(row.id),
                "user_id": row.user_id,
                "user_role": row.user_role,
                "patient_id": row.patient_id,
                "endpoint": row.endpoint,
                "ip_address": row.ip_address,
                "accessed_at": row.accessed_at.isoformat() if row.accessed_at else None,
            }
            for row in rows
        ],
    }


@router.post("/password/validate")
async def validate_password(
    body: PasswordStrengthRequest,
):
    """Validate password strength (no auth required — used on registration forms)."""
    is_valid, errors = validate_password_strength(body.password)
    strength = calculate_password_strength(body.password)

    return {
        "is_valid": is_valid,
        "errors": errors,
        "strength": strength,
    }


@router.post("/password/change")
async def change_password(
    body: PasswordChangeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change password with policy enforcement."""
    from app.services.auth_service import verify_password, hash_password

    # Verify current password
    if not await verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    # Prevent setting same password
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="New password must be different from current password")

    # Validate new password strength
    is_valid, errors = validate_password_strength(body.new_password)
    if not is_valid:
        raise HTTPException(status_code=400, detail={"errors": errors})

    # Check password history
    is_reused = await check_password_history(db, current_user.id, body.new_password)
    if is_reused:
        raise HTTPException(
            status_code=400,
            detail="This password was used recently. Please choose a different password.",
        )

    # Hash and save new password
    new_hash = await hash_password(body.new_password)
    current_user.password_hash = new_hash
    current_user.password_change_required = False

    # Update last_password_change
    from datetime import datetime, timezone
    await db.execute(text(
        "UPDATE users SET last_password_change = NOW() WHERE id = :uid"
    ), {"uid": str(current_user.id)})

    # Save to history
    await save_password_to_history(db, current_user.id, new_hash)
    await db.commit()

    return {"success": True, "message": "Password changed successfully"}


@router.get("/session/status")
async def session_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check session validity and remaining time."""
    is_valid, seconds_remaining = await check_session_valid(db, current_user.id)
    await record_session_activity(db, current_user.id)

    return {
        "valid": is_valid,
        "seconds_remaining": seconds_remaining,
        "timeout_minutes": 15,
    }


@router.post("/admin/unlock-account/{user_id}")
async def unlock_account(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """Admin: unlock a locked account."""
    success = await admin_unlock_account(db, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
    await db.commit()
    return {"success": True, "message": "Account unlocked"}
