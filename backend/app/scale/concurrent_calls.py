"""
Concurrent call handling manager — controls max simultaneous calls.

Uses asyncio primitives for thread-safe tracking of active calls.
Singleton pattern so all routes share one manager instance.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ActiveCall:
    call_id: str
    practice_id: str
    caller_phone: str
    start_time: float
    status: str = "active"


class ConcurrentCallManager:
    """Manages concurrent call slots with capacity enforcement."""

    _instance: Optional["ConcurrentCallManager"] = None

    def __init__(self, max_concurrent: int = 20):
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._lock = asyncio.Lock()
        self._active: dict[str, ActiveCall] = {}
        self._peak_count = 0
        self._total_handled = 0
        self._rejected_count = 0
        self._total_duration = 0.0

    @classmethod
    def get_instance(cls, max_concurrent: int = 20) -> "ConcurrentCallManager":
        if cls._instance is None:
            cls._instance = cls(max_concurrent)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton — for testing only."""
        cls._instance = None

    async def acquire_slot(
        self, call_id: str, practice_id: str, caller_phone: str
    ) -> bool:
        """Try to acquire a call slot. Returns False if at capacity."""
        acquired = self._semaphore._value > 0
        if not acquired:
            async with self._lock:
                self._rejected_count += 1
            logger.warning(
                "Call rejected — at capacity (%d/%d): call=%s practice=%s",
                self._max_concurrent,
                self._max_concurrent,
                call_id,
                practice_id,
            )
            return False

        await self._semaphore.acquire()
        async with self._lock:
            self._active[call_id] = ActiveCall(
                call_id=call_id,
                practice_id=practice_id,
                caller_phone=caller_phone,
                start_time=time.monotonic(),
            )
            current_count = len(self._active)
            if current_count > self._peak_count:
                self._peak_count = current_count
            self._total_handled += 1

        logger.info(
            "Call slot acquired: call=%s practice=%s active=%d/%d",
            call_id,
            practice_id,
            current_count,
            self._max_concurrent,
        )
        return True

    async def release_slot(self, call_id: str) -> None:
        """Release a call slot when the call ends."""
        async with self._lock:
            call = self._active.pop(call_id, None)
            if call:
                duration = time.monotonic() - call.start_time
                self._total_duration += duration
                logger.info(
                    "Call slot released: call=%s duration=%.1fs active=%d/%d",
                    call_id,
                    duration,
                    len(self._active),
                    self._max_concurrent,
                )

        self._semaphore.release()

    async def get_active_calls(self) -> list[dict]:
        """Return info about all currently active calls."""
        async with self._lock:
            now = time.monotonic()
            return [
                {
                    "call_id": c.call_id,
                    "practice_id": c.practice_id,
                    "caller_phone": c.caller_phone,
                    "duration_seconds": round(now - c.start_time, 1),
                    "status": c.status,
                }
                for c in self._active.values()
            ]

    async def get_stats(self) -> dict:
        """Return call handling statistics."""
        async with self._lock:
            active_count = len(self._active)
            avg_duration = (
                round(self._total_duration / self._total_handled, 1)
                if self._total_handled > 0
                else 0.0
            )
            return {
                "active_count": active_count,
                "max_concurrent": self._max_concurrent,
                "peak_count": self._peak_count,
                "total_handled": self._total_handled,
                "rejected_count": self._rejected_count,
                "avg_duration_seconds": avg_duration,
                "utilization_pct": round(
                    active_count / self._max_concurrent * 100, 1
                ),
            }
