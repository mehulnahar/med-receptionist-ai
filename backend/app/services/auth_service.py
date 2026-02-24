import asyncio
import bcrypt
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from uuid import UUID
from app.config import get_settings

# Refresh tokens live much longer than access tokens (7 days default)
_REFRESH_TOKEN_EXPIRE_DAYS = 7


async def hash_password(password: str) -> str:
    """Hash password in a thread to avoid blocking the async event loop.

    bcrypt is intentionally CPU-heavy (~100ms). Running it on the main
    event loop blocks all concurrent requests during that time.
    """
    return await asyncio.to_thread(
        lambda: bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    )


async def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password in a thread to avoid blocking the async event loop."""
    return await asyncio.to_thread(
        lambda: bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    )


def create_access_token(user_id: UUID, email: str, role: str, practice_id: UUID | None = None) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRY_MINUTES)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "practice_id": str(practice_id) if practice_id else None,
        "type": "access",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def create_refresh_token(user_id: UUID) -> str:
    """Create a long-lived refresh token containing only the user ID."""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(days=_REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def decode_access_token(token: str) -> dict | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        # Reject refresh tokens being used as access tokens
        if payload.get("type") == "refresh":
            return None
        return payload
    except JWTError:
        return None


def decode_refresh_token(token: str) -> dict | None:
    """Decode and validate a refresh token. Returns payload or None."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        if payload.get("type") != "refresh":
            return None
        return payload
    except JWTError:
        return None


def create_mfa_token(user_id: UUID) -> str:
    """Create a short-lived token for MFA verification step (5 min)."""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=5)
    payload = {
        "sub": str(user_id),
        "type": "mfa_challenge",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def decode_mfa_token(token: str) -> dict | None:
    """Decode and validate an MFA challenge token."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        if payload.get("type") != "mfa_challenge":
            return None
        return payload
    except JWTError:
        return None
