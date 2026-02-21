"""Simple in-memory TTL cache for frequently-read, rarely-written data.

Used primarily for PracticeConfig which is read on every API call
but only changes when an admin updates settings.
"""

import time
from typing import Any
from uuid import UUID


class TTLCache:
    """Coroutine-safe in-memory cache with per-key TTL expiry.

    Safe to use from async code (single-threaded event loop). Not thread-safe.
    """

    def __init__(self, default_ttl: int = 300):
        """
        Parameters
        ----------
        default_ttl : int
            Default time-to-live in seconds (default 5 minutes).
        """
        self._store: dict[str, tuple[Any, float]] = {}
        self._default_ttl = default_ttl

    def get(self, key: str) -> Any | None:
        """Return cached value if present and not expired, else None."""
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store a value with optional custom TTL."""
        expires_at = time.monotonic() + (ttl if ttl is not None else self._default_ttl)
        self._store[key] = (value, expires_at)

    def invalidate(self, key: str) -> None:
        """Remove a specific key from the cache."""
        self._store.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        """Remove all keys starting with a given prefix."""
        keys_to_remove = [k for k in self._store if k.startswith(prefix)]
        for k in keys_to_remove:
            del self._store[k]

    def clear(self) -> None:
        """Remove all entries."""
        self._store.clear()


# Global singleton — shared across the application
practice_config_cache = TTLCache(default_ttl=300)  # 5 minute TTL
