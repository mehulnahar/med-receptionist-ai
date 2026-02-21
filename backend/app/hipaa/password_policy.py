"""
HIPAA-compliant password policy enforcement.

Requirements:
  - Minimum 12 characters
  - Must contain uppercase, lowercase, number, special character
  - Cannot reuse last 10 passwords
  - Force password change every 90 days
  - Lock account after 5 failed login attempts
  - Unlock after 30 minutes or admin override
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Password complexity requirements
MIN_LENGTH = 12
MAX_LENGTH = 128
HISTORY_DEPTH = 10
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 30
PASSWORD_MAX_AGE_DAYS = 90

# Common weak passwords to reject (top 20)
COMMON_PASSWORDS = {
    "password1234", "administrator", "changeme1234",
    "p@ssw0rd1234", "welcome12345", "qwerty123456",
}


def validate_password_strength(password: str) -> tuple[bool, list[str]]:
    """Validate password meets HIPAA complexity requirements.

    Returns (is_valid, list_of_errors).
    """
    errors = []

    if len(password) < MIN_LENGTH:
        errors.append(f"Password must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        errors.append(f"Password must be at most {MAX_LENGTH} characters")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter")
    if not re.search(r"\d", password):
        errors.append("Password must contain at least one number")
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", password):
        errors.append("Password must contain at least one special character")
    if password.lower() in COMMON_PASSWORDS:
        errors.append("Password is too common, please choose a stronger password")

    return (len(errors) == 0, errors)


def calculate_password_strength(password: str) -> int:
    """Calculate password strength score 0-100 for frontend meter."""
    score = 0

    # Length scoring
    if len(password) >= 8:
        score += 10
    if len(password) >= 12:
        score += 15
    if len(password) >= 16:
        score += 10
    if len(password) >= 20:
        score += 5

    # Character variety
    if re.search(r"[a-z]", password):
        score += 10
    if re.search(r"[A-Z]", password):
        score += 10
    if re.search(r"\d", password):
        score += 10
    if re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", password):
        score += 15

    # Diversity bonus
    unique_chars = len(set(password))
    if unique_chars >= 8:
        score += 5
    if unique_chars >= 12:
        score += 5
    if unique_chars >= 16:
        score += 5

    return min(score, 100)


async def check_password_history(
    db: AsyncSession,
    user_id: UUID,
    new_password: str,
) -> bool:
    """Check if the new password was used in the last N passwords.

    Returns True if the password is reused (should be rejected).
    """
    from app.services.auth_service import verify_password

    result = await db.execute(
        text("""
            SELECT password_hash FROM password_history
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        {"user_id": str(user_id), "limit": HISTORY_DEPTH},
    )
    rows = result.fetchall()

    for row in rows:
        if await verify_password(new_password, row[0]):
            return True

    return False


async def save_password_to_history(
    db: AsyncSession,
    user_id: UUID,
    password_hash: str,
) -> None:
    """Save a password hash to the history table."""
    await db.execute(
        text("""
            INSERT INTO password_history (id, user_id, password_hash, created_at)
            VALUES (gen_random_uuid(), :user_id, :password_hash, NOW())
        """),
        {"user_id": str(user_id), "password_hash": password_hash},
    )
    # Prune old entries beyond HISTORY_DEPTH
    await db.execute(
        text("""
            DELETE FROM password_history
            WHERE user_id = :user_id
            AND id NOT IN (
                SELECT id FROM password_history
                WHERE user_id = :user_id
                ORDER BY created_at DESC
                LIMIT :limit
            )
        """),
        {"user_id": str(user_id), "limit": HISTORY_DEPTH},
    )


async def check_account_lockout(
    db: AsyncSession,
    user_id: UUID,
) -> tuple[bool, Optional[datetime]]:
    """Check if account is locked due to failed login attempts.

    Returns (is_locked, locked_until).
    """
    from app.models.user import User

    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        return (False, None)

    failed_attempts = getattr(user, "failed_login_attempts", 0) or 0
    locked_until = getattr(user, "locked_until", None)

    if locked_until and locked_until > datetime.now(timezone.utc):
        return (True, locked_until)

    if locked_until and locked_until <= datetime.now(timezone.utc):
        # Lockout expired — reset
        user.failed_login_attempts = 0
        user.locked_until = None
        await db.flush()
        return (False, None)

    if failed_attempts >= MAX_FAILED_ATTEMPTS:
        # Should be locked but locked_until wasn't set (edge case)
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
        await db.flush()
        return (True, user.locked_until)

    return (False, None)


async def record_failed_login(
    db: AsyncSession,
    user_id: UUID,
) -> tuple[int, Optional[datetime]]:
    """Record a failed login attempt. Returns (attempt_count, locked_until)."""
    from app.models.user import User

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return (0, None)

    failed = (getattr(user, "failed_login_attempts", 0) or 0) + 1
    user.failed_login_attempts = failed

    locked_until = None
    if failed >= MAX_FAILED_ATTEMPTS:
        locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
        user.locked_until = locked_until
        logger.warning(
            "Account locked for user %s after %d failed attempts (until %s)",
            user.email, failed, locked_until,
        )

    await db.flush()
    return (failed, locked_until)


async def reset_failed_login_attempts(
    db: AsyncSession,
    user_id: UUID,
) -> None:
    """Reset failed login counter on successful login."""
    from app.models.user import User

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.failed_login_attempts = 0
        user.locked_until = None
        await db.flush()


def is_password_expired(last_password_change: Optional[datetime]) -> bool:
    """Check if password needs to be changed (90-day max age)."""
    if not last_password_change:
        return True
    age = datetime.now(timezone.utc) - last_password_change.replace(tzinfo=timezone.utc)
    return age.days >= PASSWORD_MAX_AGE_DAYS


async def admin_unlock_account(
    db: AsyncSession,
    user_id: UUID,
) -> bool:
    """Admin override to unlock a locked account."""
    from app.models.user import User

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return False

    user.failed_login_attempts = 0
    user.locked_until = None
    await db.flush()
    logger.info("Account unlocked by admin for user %s", user.email)
    return True
