"""
TOTP Multi-Factor Authentication for HIPAA compliance.

Uses pyotp for TOTP generation/verification (Google Authenticator compatible).
"""

import hashlib
import logging
import secrets

import pyotp

logger = logging.getLogger(__name__)


def generate_totp_secret() -> str:
    """Generate a new TOTP secret key."""
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str, issuer: str = "AI Medical Receptionist") -> str:
    """Generate the otpauth:// URI for QR code scanning."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP code. Allows 1 window of clock drift."""
    if not secret or not code:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def generate_backup_codes(count: int = 10) -> list[str]:
    """Generate one-time backup codes."""
    return [secrets.token_hex(4).upper() for _ in range(count)]


def hash_backup_code(code: str) -> str:
    """Hash a backup code for storage."""
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()
