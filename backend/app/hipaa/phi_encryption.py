"""
PHI encryption utilities using AES-256-GCM.

Supports two backends:
  - "fernet": Local Fernet key (dev/staging) — existing behavior
  - "kms": AWS KMS data-key envelope encryption (production)

Usage:
    from app.hipaa.phi_encryption import encrypt_phi, decrypt_phi

    ciphertext = encrypt_phi("John Doe")
    plaintext = decrypt_phi(ciphertext)
"""

import base64
import hashlib
import logging
import os
import secrets
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

_PHI_PREFIX = "phi:"
_data_key: Optional[bytes] = None
_warned = False


def _get_data_key() -> Optional[bytes]:
    """Get or derive the 256-bit AES data key.

    In KMS mode, this would be a decrypted data key from AWS KMS.
    In fernet/local mode, derives from DB_ENCRYPTION_KEY.
    """
    global _data_key, _warned

    if _data_key is not None:
        return _data_key

    backend = os.environ.get("PHI_ENCRYPTION_BACKEND", "fernet").lower()

    if backend == "kms":
        return _get_kms_data_key()

    # Fernet/local mode — derive a 256-bit key from DB_ENCRYPTION_KEY
    key = os.environ.get("DB_ENCRYPTION_KEY", "").strip()
    if not key:
        if not _warned:
            logger.warning(
                "DB_ENCRYPTION_KEY is not set — PHI will be stored in PLAINTEXT. "
                "Set a key for encryption."
            )
            _warned = True
        return None

    # Derive a 256-bit key using SHA-256 from the Fernet key
    _data_key = hashlib.sha256(key.encode("utf-8")).digest()
    return _data_key


def _get_kms_data_key() -> Optional[bytes]:
    """Get a data key from AWS KMS using envelope encryption."""
    global _data_key

    kms_key_id = os.environ.get("AWS_KMS_KEY_ID", "").strip()
    region = os.environ.get("AWS_REGION", "us-east-1").strip()

    if not kms_key_id:
        logger.error("AWS_KMS_KEY_ID not set — cannot use KMS encryption backend")
        return None

    try:
        import boto3
        client = boto3.client("kms", region_name=region)
        response = client.generate_data_key(
            KeyId=kms_key_id,
            KeySpec="AES_256",
        )
        _data_key = response["Plaintext"]
        # Store the encrypted data key for later re-initialization
        os.environ["_KMS_ENCRYPTED_DATA_KEY"] = base64.b64encode(
            response["CiphertextBlob"]
        ).decode("ascii")
        logger.info("PHI encryption: AWS KMS data key generated successfully")
        return _data_key
    except ImportError:
        logger.error("boto3 not installed — cannot use KMS encryption backend")
        return None
    except Exception as e:
        logger.error("Failed to generate KMS data key: %s", e)
        return None


def encrypt_phi(plaintext: str) -> str:
    """Encrypt a PHI string using AES-256-GCM.

    Returns prefixed ciphertext string, or plaintext if no key is available.
    """
    if not plaintext:
        return plaintext

    key = _get_data_key()
    if key is None:
        return plaintext

    try:
        nonce = secrets.token_bytes(12)  # 96-bit nonce for GCM
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        # Pack: nonce + ciphertext, base64 encode, prefix
        packed = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
        return _PHI_PREFIX + packed
    except Exception as e:
        logger.error("PHI encryption failed: %s", e)
        return plaintext


def decrypt_phi(ciphertext: str) -> str:
    """Decrypt a PHI string encrypted with encrypt_phi().

    Returns plaintext, or the raw value if not encrypted or no key.
    """
    if not ciphertext or not ciphertext.startswith(_PHI_PREFIX):
        return ciphertext

    key = _get_data_key()
    if key is None:
        logger.warning("Cannot decrypt PHI — encryption key not available")
        return ciphertext

    try:
        packed = base64.urlsafe_b64decode(ciphertext[len(_PHI_PREFIX):])
        nonce = packed[:12]
        ct = packed[12:]
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ct, None)
        return plaintext.decode("utf-8")
    except Exception as e:
        logger.error("PHI decryption failed: %s", e)
        return ciphertext


def hash_phi_for_search(value: str) -> str:
    """Create a deterministic hash of a PHI value for search indexing.

    Uses HMAC-SHA256 with the encryption key as the HMAC key.
    This allows searching encrypted fields without decrypting all rows.
    """
    import hmac

    key = _get_data_key()
    if key is None:
        return value.lower().strip()

    normalized = value.lower().strip()
    return hmac.new(key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def is_encrypted(value: str) -> bool:
    """Check if a value is already encrypted."""
    return bool(value and value.startswith(_PHI_PREFIX))
