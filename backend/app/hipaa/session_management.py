"""
HIPAA Session Management — server-side session timeout enforcement.

Frontend handles the UX (idle timer, warning popup, auto-redirect).
Backend enforces token expiry and provides a session activity endpoint.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SESSION_TIMEOUT_MINUTES = 15
WARNING_BEFORE_TIMEOUT_MINUTES = 2


async def record_session_activity(
    db: AsyncSession,
    user_id: UUID,
) -> None:
    """Record that a user has been active (called on API requests)."""
    await db.execute(
        text("""
            INSERT INTO user_sessions (id, user_id, last_activity, created_at)
            VALUES (gen_random_uuid(), :user_id, NOW(), NOW())
            ON CONFLICT (user_id) DO UPDATE SET last_activity = NOW()
        """),
        {"user_id": str(user_id)},
    )
    await db.commit()


async def check_session_valid(
    db: AsyncSession,
    user_id: UUID,
) -> tuple[bool, Optional[int]]:
    """Check if the user's session is still valid.

    Returns (is_valid, seconds_remaining).
    """
    result = await db.execute(
        text("""
            SELECT last_activity FROM user_sessions
            WHERE user_id = :user_id
        """),
        {"user_id": str(user_id)},
    )
    row = result.fetchone()
    if not row:
        return (True, SESSION_TIMEOUT_MINUTES * 60)

    last_activity = row[0]
    if last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=timezone.utc)

    elapsed = datetime.now(timezone.utc) - last_activity
    timeout = timedelta(minutes=SESSION_TIMEOUT_MINUTES)
    remaining = timeout - elapsed

    if remaining.total_seconds() <= 0:
        return (False, 0)

    return (True, int(remaining.total_seconds()))


async def invalidate_session(
    db: AsyncSession,
    user_id: UUID,
) -> None:
    """Invalidate a user's session (on logout or timeout)."""
    await db.execute(
        text("DELETE FROM user_sessions WHERE user_id = :user_id"),
        {"user_id": str(user_id)},
    )
    await db.commit()
