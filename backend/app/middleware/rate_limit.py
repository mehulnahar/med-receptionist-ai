"""
In-memory rate limiting middleware.

Uses a dict of {IP -> list[timestamp]} to track requests per IP.

**Important**: This middleware is per-process.  When running behind nginx
(production) nginx's ``limit_req`` zones handle rate limiting across all
workers.  This middleware serves as a **secondary defence** for
single-worker dev mode or direct-to-backend access.

Set the environment variable ``RATE_LIMIT_ENABLED=false`` (or ``0``) to
disable this middleware entirely (e.g., when nginx is the sole rate limiter).
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
    - /api/auth/*     : RATE_LIMIT_AUTH     (default 20)
    - /api/admin/*    : RATE_LIMIT_ADMIN    (default 30)
    - /api/webhooks/* : RATE_LIMIT_WEBHOOKS (default 200)
    - everything else : RATE_LIMIT_GENERAL  (default 100)

    /api/health is always exempt from rate limiting.

    NOTE: This is per-worker in-memory state and will NOT be shared across
    Uvicorn workers.  In production, nginx ``limit_req`` is the primary
    rate limiter; this middleware acts as a secondary safety net.
    """

    def __init__(self, app):
        super().__init__(app)
        # {ip: [timestamp, timestamp, ...]}
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._window_seconds: float = 60.0
        self._stale_seconds: float = 300.0  # 5 minutes
        self._last_cleanup: float = time.monotonic()
        self._cleanup_interval: float = 60.0  # Time-based cleanup every 60 seconds
        # Allow disabling via env var when nginx handles rate limiting
        self._enabled = self._resolve_enabled()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_enabled() -> bool:
        """Check RATE_LIMIT_ENABLED env var (defaults to True)."""
        import os
        val = os.environ.get("RATE_LIMIT_ENABLED", "true").strip().lower()
        return val not in ("false", "0", "no", "off")

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP for rate-limiting purposes.

        Priority order (most trustworthy first):
        1. X-Real-IP — set by nginx from the actual TCP connection, not
           spoofable by the client.
        2. request.client.host — the direct TCP peer address.
        3. X-Forwarded-For (first entry) — only used as a last resort because
           it can be trivially spoofed when not behind a trusted proxy.
        4. Fingerprint hash — when no IP can be determined.

        Note: In production behind nginx, X-Real-IP is always set.
        """
        # Prefer X-Real-IP: nginx sets this from $remote_addr (TCP peer)
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        # Direct TCP peer (when not behind a proxy)
        if request.client and request.client.host:
            return request.client.host
        # Fallback: X-Forwarded-For (spoofable — only for dev/direct access)
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        # Last resort: hash of user-agent + accept-language to partition unknowns
        import hashlib
        fingerprint = (
            request.headers.get("user-agent", "") + request.headers.get("accept-language", "")
        )
        return "unknown-" + hashlib.md5(fingerprint.encode()).hexdigest()[:8]

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
        if path.startswith("/api/admin"):
            return settings.RATE_LIMIT_ADMIN
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

        # Skip entirely when disabled (nginx handles rate limiting in production)
        if not self._enabled:
            return await call_next(request)

        # Health check is always exempt
        if path == "/api/health":
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        now = time.monotonic()
        limit = self._get_limit_for_path(path)
        window_start = now - self._window_seconds

        # Time-based cleanup (every 60s instead of every N requests)
        if now - self._last_cleanup > self._cleanup_interval:
            self._cleanup_stale_entries()
            self._last_cleanup = now

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
