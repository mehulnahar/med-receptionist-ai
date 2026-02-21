"""
Tests for the HIPAA compliance modules.

Covers:
  - app.hipaa.phi_encryption  (AES-256-GCM encrypt/decrypt, hashing)
  - app.hipaa.password_policy (strength validation, expiry checks)
  - app.hipaa.session_management (session validity with mocked DB)

All tests run without a real database connection.
"""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_ENCRYPTION_KEY = "test-hipaa-key-do-not-use-in-prod"


@pytest.fixture(autouse=True)
def _reset_encryption_state(monkeypatch):
    """Ensure every test starts with a fresh encryption module state."""
    import app.hipaa.phi_encryption as mod

    # Clear the cached data key so each test can set its own env
    mod._data_key = None
    mod._warned = False
    # Default: provide a usable key; individual tests can override
    monkeypatch.setenv("DB_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    monkeypatch.setenv("PHI_ENCRYPTION_BACKEND", "fernet")
    yield
    mod._data_key = None
    mod._warned = False


# ===================================================================
# PHI Encryption Tests
# ===================================================================


class TestEncryptPhi:
    """Tests for encrypt_phi / decrypt_phi / helpers."""

    def test_encrypt_phi_returns_prefixed_string(self):
        from app.hipaa.phi_encryption import encrypt_phi

        result = encrypt_phi("John Doe")
        assert result.startswith("phi:"), (
            f"Encrypted value should start with 'phi:' prefix, got: {result!r}"
        )

    def test_decrypt_phi_reverses_encryption(self):
        from app.hipaa.phi_encryption import decrypt_phi, encrypt_phi

        original = "Jane Smith 123-45-6789"
        encrypted = encrypt_phi(original)
        decrypted = decrypt_phi(encrypted)
        assert decrypted == original

    def test_encrypt_phi_empty_returns_empty(self):
        from app.hipaa.phi_encryption import encrypt_phi

        assert encrypt_phi("") == ""

    def test_encrypt_phi_none_returns_none(self):
        from app.hipaa.phi_encryption import encrypt_phi

        # The function guards with `if not plaintext`, so None is falsy
        assert encrypt_phi(None) is None

    def test_encrypt_phi_no_key_returns_plaintext(self, monkeypatch):
        """When DB_ENCRYPTION_KEY is unset, encrypt_phi must return plaintext."""
        import app.hipaa.phi_encryption as mod

        mod._data_key = None  # force re-read of env
        monkeypatch.delenv("DB_ENCRYPTION_KEY", raising=False)

        from app.hipaa.phi_encryption import encrypt_phi

        plaintext = "sensitive data"
        assert encrypt_phi(plaintext) == plaintext

    def test_is_encrypted_checks_prefix(self):
        from app.hipaa.phi_encryption import is_encrypted

        assert is_encrypted("phi:abc123") is True
        assert is_encrypted("not encrypted") is False
        assert is_encrypted("") is False
        assert is_encrypted(None) is False

    def test_hash_phi_for_search_deterministic(self):
        from app.hipaa.phi_encryption import hash_phi_for_search

        h1 = hash_phi_for_search("test@example.com")
        h2 = hash_phi_for_search("test@example.com")
        assert h1 == h2, "Same input must produce the same hash"

    def test_hash_phi_for_search_different_inputs(self):
        from app.hipaa.phi_encryption import hash_phi_for_search

        h1 = hash_phi_for_search("alice@example.com")
        h2 = hash_phi_for_search("bob@example.com")
        assert h1 != h2, "Different inputs must produce different hashes"

    def test_encrypt_decrypt_unicode(self):
        from app.hipaa.phi_encryption import decrypt_phi, encrypt_phi

        original = "Paciente: Jose Garcia-Lopez"
        encrypted = encrypt_phi(original)
        assert encrypted.startswith("phi:")
        assert decrypt_phi(encrypted) == original


# ===================================================================
# Password Policy Tests
# ===================================================================


class TestPasswordPolicy:
    """Tests for validate_password_strength, calculate_password_strength,
    and is_password_expired."""

    def test_validate_password_strong(self):
        from app.hipaa.password_policy import validate_password_strength

        is_valid, errors = validate_password_strength("Str0ng!Pass#99")
        assert is_valid is True
        assert errors == []

    def test_validate_password_too_short(self):
        from app.hipaa.password_policy import validate_password_strength

        is_valid, errors = validate_password_strength("Sh0rt!1a")
        assert is_valid is False
        assert any("at least 12" in e for e in errors)

    def test_validate_password_missing_uppercase(self):
        from app.hipaa.password_policy import validate_password_strength

        is_valid, errors = validate_password_strength("alllowercase1!")
        assert is_valid is False
        assert any("uppercase" in e for e in errors)

    def test_validate_password_missing_lowercase(self):
        from app.hipaa.password_policy import validate_password_strength

        is_valid, errors = validate_password_strength("ALLUPPERCASE1!")
        assert is_valid is False
        assert any("lowercase" in e for e in errors)

    def test_validate_password_missing_digit(self):
        from app.hipaa.password_policy import validate_password_strength

        is_valid, errors = validate_password_strength("NoDigitsHere!!")
        assert is_valid is False
        assert any("number" in e for e in errors)

    def test_validate_password_missing_special(self):
        from app.hipaa.password_policy import validate_password_strength

        is_valid, errors = validate_password_strength("NoSpecialChar1X")
        assert is_valid is False
        assert any("special" in e for e in errors)

    def test_validate_password_common_rejected(self):
        from app.hipaa.password_policy import validate_password_strength

        is_valid, errors = validate_password_strength("password1234")
        assert is_valid is False
        assert any("common" in e.lower() for e in errors)

    def test_calculate_strength_max(self):
        from app.hipaa.password_policy import calculate_password_strength

        score = calculate_password_strength("V3ry$ecure&Long!Pass#2024xyz")
        assert score >= 80, f"Strong password should score >= 80, got {score}"

    def test_calculate_strength_weak(self):
        from app.hipaa.password_policy import calculate_password_strength

        score = calculate_password_strength("abc")
        assert score < 40, f"Weak password should score < 40, got {score}"

    def test_is_password_expired_none(self):
        from app.hipaa.password_policy import is_password_expired

        assert is_password_expired(None) is True

    def test_is_password_expired_recent(self):
        from app.hipaa.password_policy import is_password_expired

        recent = datetime.now(timezone.utc) - timedelta(days=10)
        assert is_password_expired(recent) is False

    def test_is_password_expired_old(self):
        from app.hipaa.password_policy import is_password_expired

        old = datetime.now(timezone.utc) - timedelta(days=91)
        assert is_password_expired(old) is True

    def test_is_password_expired_boundary(self):
        """Exactly 90 days should be expired (>= 90)."""
        from app.hipaa.password_policy import is_password_expired

        boundary = datetime.now(timezone.utc) - timedelta(days=90)
        assert is_password_expired(boundary) is True


# ===================================================================
# Session Management Tests (async, mocked DB)
# ===================================================================


class TestSessionManagement:
    """Tests for check_session_valid with a mocked AsyncSession."""

    @pytest.mark.asyncio
    async def test_check_session_valid_active(self):
        """An active session (last activity 5 min ago) should return True
        with positive seconds remaining."""
        from app.hipaa.session_management import check_session_valid

        last_activity = datetime.now(timezone.utc) - timedelta(minutes=5)

        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, idx: last_activity

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        is_valid, seconds_remaining = await check_session_valid(mock_db, uuid4())

        assert is_valid is True
        assert seconds_remaining is not None
        assert seconds_remaining > 0
        # Should be roughly 10 * 60 = 600 seconds (15 min timeout - 5 min elapsed)
        assert 550 <= seconds_remaining <= 650

    @pytest.mark.asyncio
    async def test_check_session_valid_expired(self):
        """A session whose last activity was 20 min ago (> 15 min timeout)
        should return (False, 0)."""
        from app.hipaa.session_management import check_session_valid

        last_activity = datetime.now(timezone.utc) - timedelta(minutes=20)

        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, idx: last_activity

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        is_valid, seconds_remaining = await check_session_valid(mock_db, uuid4())

        assert is_valid is False
        assert seconds_remaining == 0

    @pytest.mark.asyncio
    async def test_check_session_valid_no_row(self):
        """When no session row exists the function should treat it as valid
        with the full timeout remaining."""
        from app.hipaa.session_management import (
            SESSION_TIMEOUT_MINUTES,
            check_session_valid,
        )

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        is_valid, seconds_remaining = await check_session_valid(mock_db, uuid4())

        assert is_valid is True
        assert seconds_remaining == SESSION_TIMEOUT_MINUTES * 60
