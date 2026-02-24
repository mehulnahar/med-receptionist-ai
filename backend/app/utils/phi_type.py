"""
PHI-specific SQLAlchemy TypeDecorator for transparent column-level encryption.

Uses Fernet encryption (same as EncryptedString used for API keys).
PHI values are stored as 'phi:<encrypted_base64>' in the database.
On read, the prefix is stripped and the value is decrypted.
Plaintext values (without prefix) are returned as-is for backward compatibility.

Usage:
    from app.utils.phi_type import EncryptedPHI

    class Patient(Base):
        first_name = Column(EncryptedPHI(255), nullable=False)
"""

import logging
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)

PHI_PREFIX = "phi:"


class EncryptedPHI(TypeDecorator):
    """Transparent encrypt/decrypt for PHI columns using Fernet."""

    impl = String
    cache_ok = True

    def __init__(self, length: int = 500, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.impl = String(length)

    def _get_fernet(self):
        """Lazy-load Fernet cipher to avoid circular imports."""
        try:
            from app.utils.encryption import _get_fernet_key
            from cryptography.fernet import Fernet
            key = _get_fernet_key()
            return Fernet(key)
        except Exception:
            logger.warning("PHI encryption not configured — storing plaintext")
            return None

    def process_bind_param(self, value, dialect):
        """Encrypt on write."""
        if value is None:
            return None
        if isinstance(value, str) and value.startswith(PHI_PREFIX):
            return value  # Already encrypted
        fernet = self._get_fernet()
        if fernet is None:
            return value  # Fallback to plaintext
        try:
            encrypted = fernet.encrypt(value.encode("utf-8")).decode("utf-8")
            return f"{PHI_PREFIX}{encrypted}"
        except Exception:
            logger.exception("Failed to encrypt PHI value")
            return value

    def process_result_value(self, value, dialect):
        """Decrypt on read."""
        if value is None:
            return None
        if not isinstance(value, str) or not value.startswith(PHI_PREFIX):
            return value  # Plaintext (not yet encrypted)
        fernet = self._get_fernet()
        if fernet is None:
            return value
        try:
            encrypted_data = value[len(PHI_PREFIX):]
            return fernet.decrypt(encrypted_data.encode("utf-8")).decode("utf-8")
        except Exception:
            logger.exception("Failed to decrypt PHI value")
            return value
