"""Shared httpx.AsyncClient for connection pooling.

Creating a new AsyncClient per-request wastes TLS handshakes and prevents
HTTP/2 connection reuse.  This module provides a shared client that keeps
connections alive across requests and is properly closed on shutdown.
"""

import httpx

# Shared client — connection pool reused across all outbound HTTP calls
# (Vapi, Stedi, OpenAI, etc.).  Limits set to match typical concurrent load.
_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Return the shared httpx.AsyncClient, creating it lazily."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(30, connect=10),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            follow_redirects=True,
        )
    return _client


async def close_http_client() -> None:
    """Close the shared client (call from app shutdown hook)."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.close()
        _client = None
