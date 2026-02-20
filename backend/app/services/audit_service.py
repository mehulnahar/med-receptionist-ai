"""Audit logging service for HIPAA compliance.

Every access to or modification of PHI (Protected Health Information) must
be logged with: who, what, when, and from where.

Usage in routes:

    from app.services.audit_service import log_audit

    await log_audit(
        db=db,
        user=current_user,
        action="view",
        entity_type="patient",
        entity_id=patient.id,
        request=request,            # FastAPI Request (for IP)
        new_value={"name": "..."},  # optional
    )
"""
import logging
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


async def log_audit(
    db: AsyncSession,
    *,
    action: str,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    user: object | None = None,
    practice_id: UUID | None = None,
    old_value: dict | None = None,
    new_value: dict | None = None,
    request: Request | None = None,
) -> None:
    """Write an audit trail entry.

    Parameters
    ----------
    db : AsyncSession
    action : str   – e.g. "view", "create", "update", "delete", "export", "login"
    entity_type : str – e.g. "patient", "appointment", "call", "config"
    entity_id : UUID
    user : User model (has .id, .practice_id)
    practice_id : UUID – override, used when user is None (e.g. webhooks)
    old_value / new_value : dict – before/after for mutations
    request : FastAPI Request – to extract client IP
    """
    try:
        ip = None
        if request:
            # X-Forwarded-For in prod behind nginx
            ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            if not ip:
                ip = request.client.host if request.client else None

        entry = AuditLog(
            practice_id=practice_id or (getattr(user, "practice_id", None) if user else None),
            user_id=getattr(user, "id", None) if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
            ip_address=ip,
        )
        db.add(entry)
        # Don't commit — let the caller's transaction handle it.
        # The entry is flushed when the caller commits.
    except Exception:
        # Audit logging must never break the main request
        logger.exception("Failed to write audit log entry")
