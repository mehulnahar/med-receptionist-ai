"""
HIPAA Read Access Audit Logging.

Logs every time anyone views PHI data — required by HIPAA for access tracking.
The audit_read_logs table is append-only; even admins cannot delete entries.

Usage as middleware:
    from app.hipaa.audit_read_log import PHIReadAuditMiddleware
    app.add_middleware(PHIReadAuditMiddleware)
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Endpoints that contain PHI and must be audit-logged on read
PHI_READ_ENDPOINTS = (
    "/api/patients",
    "/api/appointments",
    "/api/insurance",
    "/api/refills",
    "/api/voicemails",
    "/api/calls",
    "/api/feedback",
    "/api/waitlist",
)


class PHIReadAuditMiddleware(BaseHTTPMiddleware):
    """Middleware that logs all GET requests to PHI-containing endpoints.

    Logs BEFORE returning data so all access attempts are captured,
    including unauthorized ones.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Only audit GET requests to PHI endpoints
        if request.method != "GET":
            return await call_next(request)

        path = request.url.path
        if not any(path.startswith(ep) for ep in PHI_READ_ENDPOINTS):
            return await call_next(request)

        # Extract user info from request state (set by auth middleware)
        user_id = None
        user_role = None
        practice_id = None

        # Try to get from JWT (auth middleware sets this)
        try:
            from app.services.auth_service import decode_access_token
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                payload = decode_access_token(token)
                if payload:
                    user_id = payload.get("sub")
                    user_role = payload.get("role")
                    practice_id = payload.get("practice_id")
        except Exception:
            pass

        # Extract patient_id from URL if present
        patient_id = _extract_patient_id(path, request.query_params)

        # Get client IP
        ip_address = _get_client_ip(request)

        # Get request ID
        request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())

        # Log the access BEFORE returning data
        await _log_phi_read(
            user_id=user_id,
            user_role=user_role,
            patient_id=patient_id,
            practice_id=practice_id,
            endpoint=path,
            method=request.method,
            query_params=str(request.query_params) if request.query_params else None,
            ip_address=ip_address,
            request_id=request_id,
        )

        return await call_next(request)


def _get_client_ip(request: Request) -> str:
    """Extract client IP, handling proxies."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _extract_patient_id(path: str, query_params) -> str | None:
    """Try to extract patient_id from URL path or query params."""
    # URL patterns like /api/patients/{uuid}
    parts = path.rstrip("/").split("/")
    for i, part in enumerate(parts):
        if part == "patients" and i + 1 < len(parts):
            candidate = parts[i + 1]
            try:
                uuid.UUID(candidate)
                return candidate
            except (ValueError, AttributeError):
                pass

    # Query parameter
    return query_params.get("patient_id")


async def _log_phi_read(
    user_id: str | None,
    user_role: str | None,
    patient_id: str | None,
    practice_id: str | None,
    endpoint: str,
    method: str,
    query_params: str | None,
    ip_address: str,
    request_id: str,
) -> None:
    """Insert a read access record into audit_read_logs.

    Uses a separate short-lived session to ensure the log is committed
    even if the main request fails.
    """
    try:
        from app.database import AsyncSessionLocal
        from sqlalchemy import text

        async with AsyncSessionLocal() as session:
            await session.execute(
                text("""
                    INSERT INTO audit_read_logs
                        (id, user_id, user_role, patient_id, practice_id,
                         endpoint, method, query_params, ip_address,
                         request_id, accessed_at)
                    VALUES
                        (gen_random_uuid(), :user_id, :user_role, :patient_id,
                         :practice_id, :endpoint, :method, :query_params,
                         :ip_address, :request_id, NOW())
                """),
                {
                    "user_id": user_id,
                    "user_role": user_role,
                    "patient_id": patient_id,
                    "practice_id": practice_id,
                    "endpoint": endpoint,
                    "method": method,
                    "query_params": query_params,
                    "ip_address": ip_address,
                    "request_id": request_id,
                },
            )
            await session.commit()
    except Exception as e:
        # Never let audit logging break the actual request
        logger.error("Failed to log PHI read access: %s", e)
