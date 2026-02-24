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


# --- Mutation Audit Log ---

@router.get("/audit-log/mutations")
async def get_mutation_audit_log(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: str = Query(None),
    entity_type: str = Query(None),
    start_date: str = Query(None, description="ISO date YYYY-MM-DD"),
    end_date: str = Query(None, description="ISO date YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """View mutation audit log (create, update, delete actions). HIPAA requirement."""
    practice_id = str(current_user.practice_id) if current_user.practice_id else None

    filters = []
    params: dict = {"limit": limit, "offset": offset}

    if practice_id:
        filters.append("practice_id = :practice_id")
        params["practice_id"] = practice_id
    if action:
        filters.append("action = :action")
        params["action"] = action
    if entity_type:
        filters.append("entity_type = :entity_type")
        params["entity_type"] = entity_type
    if start_date:
        filters.append("created_at >= :start_date::timestamptz")
        params["start_date"] = start_date
    if end_date:
        filters.append("created_at < (:end_date::date + interval '1 day')")
        params["end_date"] = end_date

    where_clause = ("WHERE " + " AND ".join(filters)) if filters else ""

    result = await db.execute(text(
        "SELECT id, user_id, action, entity_type, entity_id, "
        "       ip_address, user_agent, created_at "
        "FROM audit_logs "
        + where_clause + " "
        "ORDER BY created_at DESC "
        "LIMIT :limit OFFSET :offset"
    ), params)

    count_result = await db.execute(text(
        "SELECT COUNT(*) FROM audit_logs " + where_clause
    ), params)

    rows = result.fetchall()
    total = count_result.scalar()

    return {
        "total": total,
        "logs": [
            {
                "id": str(row.id),
                "user_id": str(row.user_id) if row.user_id else None,
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": str(row.entity_id) if row.entity_id else None,
                "ip_address": row.ip_address,
                "user_agent": getattr(row, "user_agent", None),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


# --- Data Retention ---

@router.get("/retention-policy")
async def get_retention_policy(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Get data retention policy for the current practice."""
    from app.hipaa.data_retention import get_retention_config
    practice_id = current_user.practice_id
    if not practice_id:
        raise HTTPException(status_code=400, detail="No practice associated")
    config = await get_retention_config(db, practice_id)
    return config


@router.put("/retention-policy")
async def update_retention_policy(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Update data retention policy."""
    practice_id = current_user.practice_id
    if not practice_id:
        raise HTTPException(status_code=400, detail="No practice associated")

    recording_days = body.get("recording_retention_days", 365)
    transcript_days = body.get("transcript_retention_days", 365)
    call_log_days = body.get("call_log_retention_days", 2555)
    audit_log_days = body.get("audit_log_retention_days", 2555)

    min_days = 2190  # 6 years HIPAA minimum
    if call_log_days < min_days:
        raise HTTPException(status_code=400, detail=f"Call log retention must be at least {min_days} days (6 years) per HIPAA")
    if audit_log_days < min_days:
        raise HTTPException(status_code=400, detail=f"Audit log retention must be at least {min_days} days (6 years) per HIPAA")

    await db.execute(text("""
        INSERT INTO data_retention_config (id, practice_id, recording_retention_days, transcript_retention_days, call_log_retention_days, audit_log_retention_days)
        VALUES (gen_random_uuid(), :pid, :rec, :trans, :call, :audit)
        ON CONFLICT (practice_id) DO UPDATE SET
            recording_retention_days = :rec,
            transcript_retention_days = :trans,
            call_log_retention_days = :call,
            audit_log_retention_days = :audit,
            updated_at = NOW()
    """), {
        "pid": str(practice_id),
        "rec": recording_days,
        "trans": transcript_days,
        "call": call_log_days,
        "audit": audit_log_days,
    })
    await db.commit()
    return {"success": True, "message": "Retention policy updated"}


# --- MFA Endpoints ---

class MFASetupResponse(BaseModel):
    secret: str
    uri: str


class MFAVerifyRequest(BaseModel):
    code: str


@router.post("/mfa/setup", response_model=MFASetupResponse)
async def mfa_setup(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate TOTP secret and URI for QR code setup."""
    from app.hipaa.mfa import generate_totp_secret, get_totp_uri

    secret = generate_totp_secret()
    uri = get_totp_uri(secret, current_user.email)

    await db.execute(text(
        "UPDATE users SET mfa_secret = :secret WHERE id = :uid"
    ), {"secret": secret, "uid": str(current_user.id)})
    await db.commit()

    return MFASetupResponse(secret=secret, uri=uri)


@router.post("/mfa/verify-setup")
async def mfa_verify_setup(
    body: MFAVerifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Verify TOTP code to complete MFA setup. Returns backup codes."""
    from app.hipaa.mfa import verify_totp, generate_backup_codes, hash_backup_code
    import json

    result = await db.execute(text(
        "SELECT mfa_secret FROM users WHERE id = :uid"
    ), {"uid": str(current_user.id)})
    row = result.fetchone()
    secret = row[0] if row else None

    if not secret:
        raise HTTPException(status_code=400, detail="MFA setup not started. Call /mfa/setup first.")

    if not verify_totp(secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid code. Please try again.")

    backup_codes = generate_backup_codes()
    hashed_codes = [hash_backup_code(c) for c in backup_codes]

    await db.execute(text(
        "UPDATE users SET mfa_enabled = TRUE, mfa_backup_codes = :codes WHERE id = :uid"
    ), {"codes": json.dumps(hashed_codes), "uid": str(current_user.id)})
    await db.commit()

    return {"success": True, "backup_codes": backup_codes, "message": "MFA enabled successfully. Save your backup codes!"}


@router.post("/mfa/disable")
async def mfa_disable(
    body: MFAVerifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disable MFA. Requires current TOTP code."""
    from app.hipaa.mfa import verify_totp

    result = await db.execute(text(
        "SELECT mfa_secret FROM users WHERE id = :uid"
    ), {"uid": str(current_user.id)})
    row = result.fetchone()
    secret = row[0] if row else None

    if not secret:
        raise HTTPException(status_code=400, detail="MFA is not enabled")

    if not verify_totp(secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid code")

    await db.execute(text(
        "UPDATE users SET mfa_enabled = FALSE, mfa_secret = NULL, mfa_backup_codes = NULL WHERE id = :uid"
    ), {"uid": str(current_user.id)})
    await db.commit()

    return {"success": True, "message": "MFA disabled"}


@router.get("/mfa/status")
async def mfa_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check MFA status for current user."""
    result = await db.execute(text(
        "SELECT mfa_enabled FROM users WHERE id = :uid"
    ), {"uid": str(current_user.id)})
    row = result.fetchone()
    enabled = row[0] if row else False
    return {"mfa_enabled": enabled}
