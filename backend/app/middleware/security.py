"""
Security middleware for request validation and response headers.

- Validates Content-Type on mutation requests (POST/PUT/PATCH)
- Enforces maximum request body size (1 MB)
- Adds hardening headers to every response
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# 1 MB in bytes
MAX_BODY_SIZE = 1_048_576

# Methods that must carry application/json
MUTATION_METHODS = {"POST", "PUT", "PATCH"}

# Path prefixes exempt from Content-Type validation (webhooks receive
# non-JSON payloads, e.g. Twilio sends application/x-www-form-urlencoded).
CONTENT_TYPE_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/api/webhooks/",
    "/api/reminders/twilio-reply",
)

# Security headers applied to every response
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cache-Control": "no-store",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Validates inbound requests and hardens outbound responses.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        # ---- Request body size check ----
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_BODY_SIZE:
                    logger.warning(
                        "Request body too large: %s bytes from %s %s",
                        content_length, method, path,
                    )
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request body too large. Maximum size is 1 MB."},
                    )
            except ValueError:
                pass  # Malformed header; let downstream handle it

        # ---- Content-Type validation for mutation methods ----
        if method in MUTATION_METHODS and not path.startswith(CONTENT_TYPE_EXEMPT_PREFIXES):
            content_type = request.headers.get("content-type", "")
            # Allow requests with no body (content-length 0 or missing)
            has_body = content_length is not None and content_length != "0"
            if has_body and "application/json" not in content_type:
                logger.warning(
                    "Invalid Content-Type '%s' for %s %s",
                    content_type, method, path,
                )
                return JSONResponse(
                    status_code=415,
                    content={
                        "detail": "Unsupported Media Type. Content-Type must be application/json.",
                    },
                )

        # ---- Call downstream ----
        response = await call_next(request)

        # ---- Add security headers ----
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value

        return response
