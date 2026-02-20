"""Symmetric encryption utilities for secrets at rest (API keys, tokens).

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` library.
The encryption key is derived from the DB_ENCRYPTION_KEY environment variable.
If no key is set, values are stored in plaintext (with a warning on startup).

Usage in SQLAlchemy models:

    from app.utils.encryption import EncryptedString
    api_key = Column(EncryptedString(255), nullable=True)

The column behaves exactly like a normal String — encrypt/decrypt is transparent.
"""
import base64
import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, TypeDecorator

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None
_warned = False


def _get_fernet() -> Fernet | None:
    """Lazily initialise the Fernet cipher from the environment."""
    global _fernet, _warned

    if _fernet is not None:
        return _fernet

    key = os.environ.get("DB_ENCRYPTION_KEY", "").strip()
    if not key:
        if not _warned:
            logger.warning(
                "DB_ENCRYPTION_KEY is not set — API keys will be stored in PLAINTEXT. "
                "Generate a key with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
            _warned = True
        return None

    try:
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
        return _fernet
    except Exception:
        logger.error("DB_ENCRYPTION_KEY is malformed — cannot initialise encryption")
        return None


class EncryptedString(TypeDecorator):
    """A String column that transparently encrypts on write and decrypts on read.

    Falls back to plaintext when DB_ENCRYPTION_KEY is not configured, which
    allows the same schema to work in development (no key) and production
    (key set).

    Encrypted values are prefixed with ``enc:`` so the code can distinguish
    between encrypted and legacy plaintext rows during migration.
    """

    impl = String
    cache_ok = True
    _ENC_PREFIX = "enc:"

    def __init__(self, length: int = 500, *args, **kwargs):
        # Encrypted output is longer than input — allocate extra space
        super().__init__(length, *args, **kwargs)

    def process_bind_param(self, value, dialect):
        """Encrypt before saving to the database."""
        if value is None:
            return None

        f = _get_fernet()
        if f is None:
            return value  # no key — plaintext fallback

        encrypted = f.encrypt(value.encode("utf-8"))
        return self._ENC_PREFIX + base64.urlsafe_b64encode(encrypted).decode("ascii")

    def process_result_value(self, value, dialect):
        """Decrypt when reading from the database."""
        if value is None:
            return None

        # Not encrypted (legacy row or no key was set when it was written)
        if not value.startswith(self._ENC_PREFIX):
            return value

        f = _get_fernet()
        if f is None:
            logger.warning("Cannot decrypt value — DB_ENCRYPTION_KEY is not set")
            return value  # return raw encrypted string (caller must handle)

        try:
            token = base64.urlsafe_b64decode(value[len(self._ENC_PREFIX):])
            return f.decrypt(token).decode("utf-8")
        except (InvalidToken, Exception):
            logger.error("Failed to decrypt value — key may have changed")
            return value  # return raw rather than crash
