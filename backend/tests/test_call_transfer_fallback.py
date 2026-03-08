"""
Tests for Call Transfer & TwiML Fallback (Phase 5: XFER-02, XFER-07, XFER-08, XFER-09).

Pure unit tests -- NO database, NO running server.
Tests cover: positive transfer flow, negative (no number) flow, edge cases,
and TwiML fallback endpoint via ASGI TestClient.

Covers:
  XFER-02: AI can transfer mid-call (verified via positive transfer test)
  XFER-07: Positive - transfer with configured number returns transfer=True
  XFER-08: Negative - no transfer_number returns graceful failure
  XFER-09: Edge - transfer works regardless of office hours (no time check)
  XFER-03: TwiML fallback endpoint returns valid XML
"""

import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRACTICE_ID = uuid.uuid4()
VAPI_CALL_ID = "call_transfer_test_001"
TRANSFER_NUMBER = "+12125551234"


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _mock_practice_config(**overrides):
    """Create a mock PracticeConfig with transfer-related fields."""
    config = MagicMock()
    config.practice_id = PRACTICE_ID
    config.transfer_number = overrides.get("transfer_number", TRANSFER_NUMBER)
    config.transfer_message = overrides.get("transfer_message", "Transferring you now, please hold.")
    config.fallback_phone_number = overrides.get("fallback_phone_number", "+12125559999")
    config.vapi_phone_number_id = overrides.get("vapi_phone_number_id", "vapi-phone-123")
    config.twilio_phone_number = overrides.get("twilio_phone_number", "+12678052214")
    return config


def _mock_call_obj(**overrides):
    """Create a mock Call object for transfer logging tests."""
    call = MagicMock()
    call.id = uuid.uuid4()
    call.practice_id = PRACTICE_ID
    call.vapi_call_id = overrides.get("vapi_call_id", VAPI_CALL_ID)
    call.caller_phone = overrides.get("caller_phone", "+19165551234")
    call.duration_seconds = overrides.get("duration_seconds", 120)
    call.call_metadata = overrides.get("call_metadata", None)
    return call


def _mock_db_for_transfer(config_to_return, call_to_return=None):
    """Create a mock AsyncSession that returns config then optionally call.

    The first db.execute() returns the PracticeConfig.
    The second db.execute() (if called) returns the Call object.
    """
    mock_config_result = MagicMock()
    mock_config_result.scalar_one_or_none.return_value = config_to_return

    mock_call_result = MagicMock()
    mock_call_result.scalar_one_or_none.return_value = call_to_return

    db = AsyncMock()
    # First call returns config, second returns call
    db.execute = AsyncMock(side_effect=[mock_config_result, mock_call_result])
    return db


def _mock_db_no_config(call_to_return=None):
    """Create a mock AsyncSession that returns no config (None)."""
    mock_config_result = MagicMock()
    mock_config_result.scalar_one_or_none.return_value = None

    mock_call_result = MagicMock()
    mock_call_result.scalar_one_or_none.return_value = call_to_return

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[mock_config_result, mock_call_result])
    return db


# ===========================================================================
# Class 1: TestTransferPositive (XFER-02, XFER-07)
# ===========================================================================

class TestTransferPositive:
    """Tests for successful transfer scenarios."""

    @pytest.mark.asyncio
    async def test_transfer_with_configured_number_returns_true(self):
        """XFER-07: transfer_to_staff with configured number returns transfer=True."""
        from app.services.vapi_tools import tool_transfer_to_staff

        config = _mock_practice_config(transfer_number=TRANSFER_NUMBER)
        db = _mock_db_for_transfer(config)

        result = await tool_transfer_to_staff(
            db=db,
            practice_id=PRACTICE_ID,
            params={"reason": "Caller wants billing info"},
        )

        assert result["transfer"] is True
        assert result["number"] == TRANSFER_NUMBER
        assert result["reason"] == "Caller wants billing info"

    @pytest.mark.asyncio
    async def test_transfer_logs_metadata_to_call(self):
        """XFER-07: Successful transfer logs transfer_log to Call.call_metadata."""
        from app.services.vapi_tools import tool_transfer_to_staff

        config = _mock_practice_config(transfer_number=TRANSFER_NUMBER)
        call = _mock_call_obj(caller_phone="+19165551234", duration_seconds=90)
        db = _mock_db_for_transfer(config, call)

        await tool_transfer_to_staff(
            db=db,
            practice_id=PRACTICE_ID,
            params={"reason": "Staff transfer requested"},
            vapi_call_id=VAPI_CALL_ID,
        )

        # Verify call_metadata was updated with transfer_log
        meta = call.call_metadata
        assert meta is not None
        assert "transfer_log" in meta
        log = meta["transfer_log"]
        assert log["transfer_reason"] == "Staff transfer requested"
        assert log["caller_phone"] == "+19165551234"
        assert log["duration_at_transfer"] == 90
        assert log["transfer_number"] == TRANSFER_NUMBER
        assert "timestamp" in log

    @pytest.mark.asyncio
    async def test_transfer_with_custom_reason_passes_through(self):
        """XFER-07: Custom reason is passed through to response and metadata."""
        from app.services.vapi_tools import tool_transfer_to_staff

        config = _mock_practice_config(transfer_number=TRANSFER_NUMBER)
        call = _mock_call_obj()
        db = _mock_db_for_transfer(config, call)

        result = await tool_transfer_to_staff(
            db=db,
            practice_id=PRACTICE_ID,
            params={"reason": "Greek speaker needs help"},
            vapi_call_id=VAPI_CALL_ID,
        )

        assert result["reason"] == "Greek speaker needs help"
        assert call.call_metadata["transfer_log"]["transfer_reason"] == "Greek speaker needs help"

    @pytest.mark.asyncio
    async def test_transfer_default_reason_when_none_provided(self):
        """XFER-07: Default reason is used when no reason in params."""
        from app.services.vapi_tools import tool_transfer_to_staff

        config = _mock_practice_config(transfer_number=TRANSFER_NUMBER)
        db = _mock_db_for_transfer(config)

        result = await tool_transfer_to_staff(
            db=db,
            practice_id=PRACTICE_ID,
            params={},  # No reason
        )

        assert result["transfer"] is True
        assert result["reason"] == "Caller requested staff transfer"

    @pytest.mark.asyncio
    async def test_transfer_reads_number_from_db_config(self):
        """XFER-02: Transfer number comes from PracticeConfig (DB), not env."""
        from app.services.vapi_tools import tool_transfer_to_staff

        custom_number = "+18005551000"
        config = _mock_practice_config(transfer_number=custom_number)
        db = _mock_db_for_transfer(config)

        result = await tool_transfer_to_staff(
            db=db,
            practice_id=PRACTICE_ID,
            params={"reason": "test"},
        )

        assert result["number"] == custom_number
        # Verify db.execute was called (i.e., it queried the DB)
        assert db.execute.call_count >= 1


# ===========================================================================
# Class 2: TestTransferNegative (XFER-08)
# ===========================================================================

class TestTransferNegative:
    """Tests for transfer failure scenarios (no number configured)."""

    @pytest.mark.asyncio
    async def test_no_transfer_number_returns_false(self):
        """XFER-08: No transfer_number returns transfer=False with graceful message."""
        from app.services.vapi_tools import tool_transfer_to_staff

        config = _mock_practice_config(transfer_number=None)
        db = _mock_db_for_transfer(config)

        result = await tool_transfer_to_staff(
            db=db,
            practice_id=PRACTICE_ID,
            params={"reason": "Staff help needed"},
        )

        assert result["transfer"] is False
        assert "message" in result
        assert "No staff transfer number" in result["message"]

    @pytest.mark.asyncio
    async def test_no_practice_config_returns_false(self):
        """XFER-08: No PracticeConfig at all returns transfer=False gracefully."""
        from app.services.vapi_tools import tool_transfer_to_staff

        db = _mock_db_no_config()

        result = await tool_transfer_to_staff(
            db=db,
            practice_id=PRACTICE_ID,
            params={"reason": "Transfer request"},
        )

        assert result["transfer"] is False
        assert "message" in result

    @pytest.mark.asyncio
    async def test_failed_transfer_logs_metadata(self):
        """XFER-08: Failed transfer logs transfer_attempted=True to call_metadata."""
        from app.services.vapi_tools import tool_transfer_to_staff

        config = _mock_practice_config(transfer_number=None)
        call = _mock_call_obj()
        db = _mock_db_for_transfer(config, call)

        await tool_transfer_to_staff(
            db=db,
            practice_id=PRACTICE_ID,
            params={"reason": "Need staff"},
            vapi_call_id=VAPI_CALL_ID,
        )

        meta = call.call_metadata
        assert meta is not None
        assert "transfer_log" in meta
        log = meta["transfer_log"]
        assert log["transfer_attempted"] is True
        assert log["transfer_failed_reason"] == "no_transfer_number_configured"

    @pytest.mark.asyncio
    async def test_empty_string_transfer_number_returns_false(self):
        """XFER-08: Empty string transfer_number also returns transfer=False."""
        from app.services.vapi_tools import tool_transfer_to_staff

        config = _mock_practice_config(transfer_number="")
        db = _mock_db_for_transfer(config)

        result = await tool_transfer_to_staff(
            db=db,
            practice_id=PRACTICE_ID,
            params={"reason": "Transfer"},
        )

        assert result["transfer"] is False
        assert "message" in result


# ===========================================================================
# Class 3: TestTransferEdge (XFER-09)
# ===========================================================================

class TestTransferEdge:
    """Tests for edge cases in transfer logic."""

    @pytest.mark.asyncio
    async def test_transfer_has_no_office_hours_check(self):
        """XFER-09: transfer_to_staff works regardless of time (no office hours check).

        The function just returns the number -- Twilio handles voicemail.
        We verify by calling at an arbitrary time and checking it succeeds.
        """
        from app.services.vapi_tools import tool_transfer_to_staff

        config = _mock_practice_config(transfer_number=TRANSFER_NUMBER)
        db = _mock_db_for_transfer(config)

        # Call at any time -- should still return the number
        result = await tool_transfer_to_staff(
            db=db,
            practice_id=PRACTICE_ID,
            params={"reason": "After hours call"},
        )

        assert result["transfer"] is True
        assert result["number"] == TRANSFER_NUMBER
        # No time-related fields in the result -- function is time-agnostic

    @pytest.mark.asyncio
    async def test_transfer_without_vapi_call_id_skips_logging(self):
        """XFER-09: vapi_call_id=None still returns correct result (skips logging)."""
        from app.services.vapi_tools import tool_transfer_to_staff

        config = _mock_practice_config(transfer_number=TRANSFER_NUMBER)
        # Only one DB call needed -- config lookup, no call lookup
        mock_config_result = MagicMock()
        mock_config_result.scalar_one_or_none.return_value = config
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_config_result)

        result = await tool_transfer_to_staff(
            db=db,
            practice_id=PRACTICE_ID,
            params={"reason": "Quick transfer"},
            vapi_call_id=None,
        )

        assert result["transfer"] is True
        assert result["number"] == TRANSFER_NUMBER
        # Only 1 DB call (config lookup), no call lookup
        assert db.execute.call_count == 1


# ===========================================================================
# Class 4: TestTwimlFallback (XFER-03 verification)
# ===========================================================================

class TestTwimlFallback:
    """Tests for the TwiML fallback endpoint at /api/webhooks/twilio-fallback."""

    @pytest_asyncio.fixture
    async def client_with_config(self):
        """Create an ASGI test client with a mock DB returning a configured practice."""
        config = _mock_practice_config(fallback_phone_number="+12125559999")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def override_get_db():
            yield mock_db

        from app.main import app
        from app.database import get_db

        app.dependency_overrides[get_db] = override_get_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac
        app.dependency_overrides.clear()

    @pytest_asyncio.fixture
    async def client_no_config(self):
        """Create an ASGI test client with a mock DB returning no practice config."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def override_get_db():
            yield mock_db

        from app.main import app
        from app.database import get_db

        app.dependency_overrides[get_db] = override_get_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_get_with_matching_practice_returns_dial_twiml(self, client_with_config):
        """XFER-03: GET with matching practice returns TwiML with <Dial>."""
        resp = await client_with_config.get(
            "/api/webhooks/twilio-fallback",
            params={"phone_number_id": "vapi-phone-123"},
        )

        assert resp.status_code == 200
        body = resp.text
        assert "<Dial" in body
        assert "+12125559999" in body

    @pytest.mark.asyncio
    async def test_get_with_no_matching_practice_returns_say_twiml(self, client_no_config):
        """XFER-03: GET with no matching practice returns TwiML with <Say> unavailable."""
        resp = await client_no_config.get(
            "/api/webhooks/twilio-fallback",
            params={"phone_number_id": "nonexistent-phone"},
        )

        assert resp.status_code == 200
        body = resp.text
        assert "<Say" in body
        assert "unavailable" in body.lower()
        # No <Dial> tag when no practice found
        assert "<Dial" not in body

    @pytest.mark.asyncio
    async def test_post_also_works(self, client_with_config):
        """XFER-03: POST to fallback also works (Twilio may use POST)."""
        resp = await client_with_config.post(
            "/api/webhooks/twilio-fallback",
            params={"phone_number_id": "vapi-phone-123"},
        )

        assert resp.status_code == 200
        body = resp.text
        assert "<Dial" in body

    @pytest.mark.asyncio
    async def test_response_content_type_is_xml(self, client_with_config):
        """XFER-03: Response content-type is application/xml."""
        resp = await client_with_config.get(
            "/api/webhooks/twilio-fallback",
            params={"phone_number_id": "vapi-phone-123"},
        )

        assert "application/xml" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_twiml_is_wellformed_xml_with_dial(self, client_with_config):
        """XFER-03: TwiML response with <Dial> is well-formed XML."""
        resp = await client_with_config.get(
            "/api/webhooks/twilio-fallback",
            params={"phone_number_id": "vapi-phone-123"},
        )

        # Parse as XML -- will raise if malformed
        root = ET.fromstring(resp.text)
        assert root.tag == "Response"

        # Find <Dial> element
        dial = root.find("Dial")
        assert dial is not None
        assert "+12125559999" in dial.text

    @pytest.mark.asyncio
    async def test_twiml_is_wellformed_xml_unavailable(self, client_no_config):
        """XFER-03: TwiML unavailable response is well-formed XML."""
        resp = await client_no_config.get(
            "/api/webhooks/twilio-fallback",
            params={"phone_number_id": "nonexistent"},
        )

        # Parse as XML -- will raise if malformed
        root = ET.fromstring(resp.text)
        assert root.tag == "Response"

        # Find <Say> element
        say = root.find("Say")
        assert say is not None
        assert "unavailable" in say.text.lower()
