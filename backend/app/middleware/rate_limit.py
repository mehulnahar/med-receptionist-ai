"""
In-memory rate limiting middleware.

Uses a dict of {IP -> list[timestamp]} to track requests per IP.
Designed for single-instance deployment (Railway).
"""

import logging
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Per-IP rate limiter with endpoint-specific limits.

    Limits (requests per minute):
    - /api/auth/*     : RATE_LIMIT_AUTH     (default 10)
    - /api/webhooks/* : RATE_LIMIT_WEBHOOKS (default 200)
    - everything else : RATE_LIMIT_GENERAL  (default 100)

    /api/health is always exempt from rate limiting.
    """

    def __init__(self, app):
        super().__init__(app)
        # {ip: [timestamp, timestamp, ...]}
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._total_requests: int = 0
        self._cleanup_threshold: int = 1000
        self._window_seconds: float = 60.0
        self._stale_seconds: float = 300.0  # 5 minutes

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP, respecting X-Forwarded-For behind Railway proxy."""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # First IP in the chain is the real client
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _get_limit_for_path(self, path: str) -> int:
        """Return the per-minute rate limit based on the request path.

        /api/auth/me is a read-only session check called on every page load,
        so it uses the general (100/min) limit instead of the strict auth
        (10/min) limit reserved for login/register/password-reset endpoints.
        """
        if path.startswith("/api/auth"):
            # Read-only profile endpoint — treat like a normal API call
            if path in ("/api/auth/me", "/api/auth/me/"):
                return settings.RATE_LIMIT_GENERAL
            return settings.RATE_LIMIT_AUTH
        if path.startswith("/api/webhooks"):
            return settings.RATE_LIMIT_WEBHOOKS
        return settings.RATE_LIMIT_GENERAL

    def _cleanup_stale_entries(self) -> None:
        """Remove entries older than 5 minutes to prevent memory leaks."""
        cutoff = time.monotonic() - self._stale_seconds
        stale_ips = []
        for ip, timestamps in self._requests.items():
            # Filter out stale timestamps
            self._requests[ip] = [t for t in timestamps if t > cutoff]
            if not self._requests[ip]:
                stale_ips.append(ip)
        for ip in stale_ips:
            del self._requests[ip]

    # ------------------------------------------------------------------
    # Middleware dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Health check is always exempt
        if path == "/api/health":
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        now = time.monotonic()
        limit = self._get_limit_for_path(path)
        window_start = now - self._window_seconds

        # Periodic cleanup
        self._total_requests += 1
        if self._total_requests % self._cleanup_threshold == 0:
            self._cleanup_stale_entries()

        # Prune timestamps outside the current window for this IP
        timestamps = self._requests[client_ip]
        self._requests[client_ip] = [t for t in timestamps if t > window_start]
        timestamps = self._requests[client_ip]

        if len(timestamps) >= limit:
            # Calculate how long until the oldest request in the window expires
            retry_after = int(timestamps[0] - window_start) + 1
            if retry_after < 1:
                retry_after = 1

            logger.warning(
                "Rate limit exceeded: IP=%s path=%s count=%d limit=%d",
                client_ip, path, len(timestamps), limit,
            )

            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please try again later.",
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        # Record this request
        self._requests[client_ip].append(now)

        # Add rate limit info headers to the response
        response = await call_next(request)
        remaining = max(0, limit - len(self._requests[client_ip]))
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
