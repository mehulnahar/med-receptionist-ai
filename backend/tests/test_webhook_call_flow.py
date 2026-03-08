"""
Tests for Vapi Webhook Call Flow (Phase 3: HOOK-01 through HOOK-08).

Pure unit tests -- NO database, NO running server.
Tests cover: signature verification, dispatch routing, end-of-call persistence,
practice resolution, malformed payload handling, and concurrent call safety.

Covers:
  HOOK-01: Webhook dispatch routes each message type to the correct handler
  HOOK-02: Valid HMAC-SHA256 and x-vapi-secret signatures are accepted
  HOOK-03: End-of-call report saves all 5 required fields
  HOOK-04: Practice resolved from phone number
  HOOK-05: Structured data extraction (caller_intent, caller_sentiment, language)
  HOOK-06: Invalid/missing signatures are rejected
  HOOK-07: Malformed payloads return 400 (not 500)
  HOOK-08: Concurrent calls to the same practice don't corrupt data
"""

import asyncio
import hashlib
import hmac as hmac_mod
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_SECRET = "test-webhook-secret-abc123"
PRACTICE_ID = uuid.uuid4()
VAPI_CALL_ID = "call_abc123def456"


def _make_hmac_signature(body_bytes: bytes, secret: str = FAKE_SECRET) -> str:
    """Compute HMAC-SHA256 hex digest for a raw body."""
    return hmac_mod.new(
        secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()


def _build_webhook_body(msg_type: str, extra_message: dict | None = None) -> dict:
    """Build a minimal valid Vapi webhook body with the given message type."""
    message = {
        "type": msg_type,
        "call": {
            "id": VAPI_CALL_ID,
            "orgId": "org-123",
            "type": "inboundPhoneCall",
            "status": "in-progress",
            "phoneNumber": {"number": "+12678052214"},
            "customer": {"number": "+19165551234"},
        },
    }
    if extra_message:
        message.update(extra_message)
    return {"message": message}


def _mock_settings(
    secret: str = FAKE_SECRET,
    app_env: str = "development",
) -> MagicMock:
    """Return a mock Settings object with the given VAPI_WEBHOOK_SECRET and APP_ENV."""
    settings = MagicMock()
    settings.VAPI_WEBHOOK_SECRET = secret
    settings.APP_ENV = app_env
    return settings


# ===========================================================================
# Class 1: TestWebhookSignatureVerification (HOOK-02, HOOK-06)
# ===========================================================================

class TestWebhookSignatureVerification:
    """Tests for _verify_vapi_signature function directly."""

    def _verify(self, raw_body: bytes, signature: str | None = None, secret_header: str | None = None):
        """Import and call _verify_vapi_signature."""
        from app.routes.webhooks import _verify_vapi_signature
        return _verify_vapi_signature(raw_body, signature, secret_header)

    # --- HOOK-02: Valid signatures accepted ---

    @patch("app.routes.webhooks.get_settings")
    def test_valid_hmac_signature_accepted(self, mock_get_settings):
        """HOOK-02: Valid HMAC-SHA256 signature returns True."""
        mock_get_settings.return_value = _mock_settings(secret=FAKE_SECRET)
        body = b'{"message": {"type": "assistant-request"}}'
        sig = _make_hmac_signature(body)
        assert self._verify(body, signature=sig) is True

    @patch("app.routes.webhooks.get_settings")
    def test_valid_secret_token_accepted(self, mock_get_settings):
        """HOOK-02: Valid x-vapi-secret token returns True."""
        mock_get_settings.return_value = _mock_settings(secret=FAKE_SECRET)
        body = b'{"message": {"type": "status-update"}}'
        assert self._verify(body, secret_header=FAKE_SECRET) is True

    # --- HOOK-06: Invalid / missing signatures rejected ---

    @patch("app.routes.webhooks.get_settings")
    def test_invalid_hmac_signature_rejected(self, mock_get_settings):
        """HOOK-06: Invalid HMAC signature returns False."""
        mock_get_settings.return_value = _mock_settings(secret=FAKE_SECRET)
        body = b'{"message": {"type": "status-update"}}'
        assert self._verify(body, signature="bad-signature") is False

    @patch("app.routes.webhooks.get_settings")
    def test_invalid_secret_token_rejected(self, mock_get_settings):
        """HOOK-06: Invalid x-vapi-secret token returns False."""
        mock_get_settings.return_value = _mock_settings(secret=FAKE_SECRET)
        body = b'{"message": {"type": "status-update"}}'
        assert self._verify(body, secret_header="wrong-token") is False

    @patch("app.routes.webhooks.get_settings")
    def test_missing_both_headers_rejected(self, mock_get_settings):
        """HOOK-06: Missing both auth headers (secret configured) returns False."""
        mock_get_settings.return_value = _mock_settings(secret=FAKE_SECRET)
        body = b'{"message": {"type": "status-update"}}'
        assert self._verify(body, signature=None, secret_header=None) is False

    @patch("app.routes.webhooks.get_settings")
    def test_no_secret_configured_dev_mode_skips(self, mock_get_settings):
        """HOOK-02: No secret configured in dev mode returns True (skip verification)."""
        mock_get_settings.return_value = _mock_settings(secret="", app_env="development")
        body = b'{"message": {"type": "status-update"}}'
        assert self._verify(body, signature=None, secret_header=None) is True

    @patch("app.routes.webhooks.get_settings")
    def test_no_secret_configured_production_rejects_all(self, mock_get_settings):
        """HOOK-06: No secret configured in production returns False (reject all)."""
        mock_get_settings.return_value = _mock_settings(secret="", app_env="production")
        body = b'{"message": {"type": "status-update"}}'
        assert self._verify(body, signature=None, secret_header=None) is False

    @patch("app.routes.webhooks.get_settings")
    def test_hmac_takes_priority_over_secret_header(self, mock_get_settings):
        """When HMAC signature is present, it is checked first even if secret_header is also present."""
        mock_get_settings.return_value = _mock_settings(secret=FAKE_SECRET)
        body = b'{"message": {"type": "test"}}'
        good_sig = _make_hmac_signature(body)
        # Both provided: valid HMAC + invalid secret -> should pass (HMAC wins)
        assert self._verify(body, signature=good_sig, secret_header="wrong") is True

    @patch("app.routes.webhooks.get_settings")
    def test_bad_hmac_fails_even_with_good_secret_header(self, mock_get_settings):
        """When HMAC signature is present but invalid, request is rejected even if secret_header is valid."""
        mock_get_settings.return_value = _mock_settings(secret=FAKE_SECRET)
        body = b'{"message": {"type": "test"}}'
        # Bad HMAC + good secret -> should fail (HMAC checked first, fails)
        assert self._verify(body, signature="bad-sig", secret_header=FAKE_SECRET) is False


# ===========================================================================
# Class 2: TestWebhookDispatch (HOOK-01)
# ===========================================================================

class TestWebhookDispatch:
    """Tests that each message type dispatches to the correct handler.

    Uses the ASGI TestClient to send real HTTP requests to the FastAPI app
    with signature verification disabled (dev mode, no secret configured).
    """

    @pytest_asyncio.fixture
    async def client(self):
        """Create an ASGI test client with dev-mode settings (no signature check)."""
        with patch("app.routes.webhooks.get_settings") as mock_gs:
            mock_gs.return_value = _mock_settings(secret="", app_env="development")

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
                yield ac

    @pytest.mark.asyncio
    @patch("app.routes.webhooks._resolve_practice_id", new_callable=AsyncMock, return_value=PRACTICE_ID)
    @patch("app.routes.webhooks._handle_assistant_request", new_callable=AsyncMock)
    async def test_assistant_request_dispatches(self, mock_handler, mock_resolve, client):
        """HOOK-01: assistant-request type calls _handle_assistant_request."""
        from fastapi.responses import JSONResponse
        mock_handler.return_value = JSONResponse(status_code=200, content={"assistant": None})

        body = _build_webhook_body("assistant-request")
        resp = await client.post("/api/webhooks/vapi", json=body)
        assert resp.status_code == 200
        mock_handler.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.routes.webhooks._resolve_practice_id", new_callable=AsyncMock, return_value=PRACTICE_ID)
    @patch("app.routes.webhooks._handle_tool_calls", new_callable=AsyncMock)
    async def test_tool_calls_dispatches(self, mock_handler, mock_resolve, client):
        """HOOK-01: tool-calls type calls _handle_tool_calls."""
        from fastapi.responses import JSONResponse
        mock_handler.return_value = JSONResponse(status_code=200, content={"results": []})

        body = _build_webhook_body("tool-calls")
        resp = await client.post("/api/webhooks/vapi", json=body)
        assert resp.status_code == 200
        mock_handler.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.routes.webhooks._resolve_practice_id", new_callable=AsyncMock, return_value=PRACTICE_ID)
    @patch("app.routes.webhooks._handle_status_update", new_callable=AsyncMock)
    async def test_status_update_dispatches(self, mock_handler, mock_resolve, client):
        """HOOK-01: status-update type calls _handle_status_update."""
        from fastapi.responses import JSONResponse
        mock_handler.return_value = JSONResponse(status_code=200, content={})

        body = _build_webhook_body("status-update", {"status": "in-progress"})
        resp = await client.post("/api/webhooks/vapi", json=body)
        assert resp.status_code == 200
        mock_handler.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.routes.webhooks._resolve_practice_id", new_callable=AsyncMock, return_value=PRACTICE_ID)
    @patch("app.routes.webhooks._handle_end_of_call_report", new_callable=AsyncMock)
    async def test_end_of_call_report_dispatches(self, mock_handler, mock_resolve, client):
        """HOOK-01: end-of-call-report type calls _handle_end_of_call_report."""
        from fastapi.responses import JSONResponse
        mock_handler.return_value = JSONResponse(status_code=200, content={})

        body = _build_webhook_body("end-of-call-report")
        resp = await client.post("/api/webhooks/vapi", json=body)
        assert resp.status_code == 200
        mock_handler.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.routes.webhooks._resolve_practice_id", new_callable=AsyncMock, return_value=PRACTICE_ID)
    async def test_unknown_type_returns_200(self, mock_resolve, client):
        """HOOK-01: Unknown message type returns 200 (no crash)."""
        body = _build_webhook_body("some-future-type")
        resp = await client.post("/api/webhooks/vapi", json=body)
        assert resp.status_code == 200


# ===========================================================================
# Class 3: TestEndOfCallReportPersistence (HOOK-03, HOOK-05)
# ===========================================================================

class TestEndOfCallReportPersistence:
    """Tests for save_end_of_call_report with mock DB session and Call object."""

    def _make_mock_call(self, **overrides):
        """Create a mock Call object with default attributes."""
        call = MagicMock()
        call.id = uuid.uuid4()
        call.practice_id = PRACTICE_ID
        call.vapi_call_id = VAPI_CALL_ID
        call.transcription = None
        call.recording_url = None
        call.ai_summary = None
        call.vapi_cost = None
        call.structured_data = None
        call.caller_intent = None
        call.caller_sentiment = None
        call.language = "en"
        call.status = "in-progress"
        call.outcome = None
        call.call_metadata = None
        call.success_evaluation = None
        call.duration_seconds = None
        call.started_at = None
        call.ended_at = None
        for k, v in overrides.items():
            setattr(call, k, v)
        return call

    def _make_mock_db(self, call_to_return):
        """Create a mock AsyncSession that returns the given call on query."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = call_to_return

        db = AsyncMock()
        db.execute.return_value = mock_result
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_all_five_fields_set(self):
        """HOOK-03: All 5 required fields (recording_url, transcript, summary, structured_data, cost) are set on the call object."""
        from app.services.call_service import save_end_of_call_report

        call = self._make_mock_call()
        db = self._make_mock_db(call)

        result = await save_end_of_call_report(
            db=db,
            vapi_call_id=VAPI_CALL_ID,
            transcript="Patient asked about appointment",
            recording_url="https://storage.vapi.ai/recordings/abc.wav",
            summary="Caller wanted to book an appointment for next week.",
            cost=0.15,
            structured_data={"caller_intent": "book_appointment", "caller_sentiment": "positive", "language": "english"},
        )

        assert result is not None
        assert call.transcription == "Patient asked about appointment"
        assert call.recording_url == "https://storage.vapi.ai/recordings/abc.wav"
        assert call.ai_summary == "Caller wanted to book an appointment for next week."
        assert call.vapi_cost == Decimal("0.15")
        assert call.structured_data == {"caller_intent": "book_appointment", "caller_sentiment": "positive", "language": "english"}

    @pytest.mark.asyncio
    async def test_structured_data_extracts_fields(self):
        """HOOK-05: structured_data extracts caller_intent, caller_sentiment, and language."""
        from app.services.call_service import save_end_of_call_report

        call = self._make_mock_call()
        db = self._make_mock_db(call)

        await save_end_of_call_report(
            db=db,
            vapi_call_id=VAPI_CALL_ID,
            structured_data={
                "caller_intent": "cancel_appointment",
                "caller_sentiment": "frustrated",
                "language": "spanish",
            },
        )

        assert call.caller_intent == "cancel_appointment"
        assert call.caller_sentiment == "frustrated"
        assert call.language == "es"  # "spanish" maps to "es"

    @pytest.mark.asyncio
    async def test_language_mapping_english(self):
        """HOOK-05: Language 'english' maps to 'en'."""
        from app.services.call_service import save_end_of_call_report

        call = self._make_mock_call()
        db = self._make_mock_db(call)

        await save_end_of_call_report(
            db=db,
            vapi_call_id=VAPI_CALL_ID,
            structured_data={"language": "english"},
        )

        assert call.language == "en"

    @pytest.mark.asyncio
    async def test_language_mapping_unknown_language_truncated(self):
        """HOOK-05: Unknown language is stored truncated to 5 chars."""
        from app.services.call_service import save_end_of_call_report

        call = self._make_mock_call()
        db = self._make_mock_db(call)

        await save_end_of_call_report(
            db=db,
            vapi_call_id=VAPI_CALL_ID,
            structured_data={"language": "mandarin"},
        )

        assert call.language == "manda"  # truncated to 5 chars

    @pytest.mark.asyncio
    async def test_cost_stored_as_decimal(self):
        """HOOK-03: Cost is converted to Decimal for accurate storage."""
        from app.services.call_service import save_end_of_call_report

        call = self._make_mock_call()
        db = self._make_mock_db(call)

        await save_end_of_call_report(
            db=db,
            vapi_call_id=VAPI_CALL_ID,
            cost=0.0832,
        )

        assert isinstance(call.vapi_cost, Decimal)
        assert call.vapi_cost == Decimal("0.0832")

    @pytest.mark.asyncio
    async def test_none_values_dont_overwrite_existing_data(self):
        """HOOK-03: None values do not overwrite existing data on the call."""
        from app.services.call_service import save_end_of_call_report

        call = self._make_mock_call(
            transcription="Existing transcript",
            recording_url="https://example.com/existing.wav",
            ai_summary="Existing summary",
            vapi_cost=Decimal("0.10"),
        )
        db = self._make_mock_db(call)

        await save_end_of_call_report(
            db=db,
            vapi_call_id=VAPI_CALL_ID,
            transcript=None,
            recording_url=None,
            summary=None,
            cost=None,
        )

        # Existing values preserved (not overwritten with None)
        assert call.transcription == "Existing transcript"
        assert call.recording_url == "https://example.com/existing.wav"
        assert call.ai_summary == "Existing summary"
        assert call.vapi_cost == Decimal("0.10")

    @pytest.mark.asyncio
    async def test_call_not_found_returns_none(self):
        """HOOK-03: Returns None when vapi_call_id doesn't match any call."""
        from app.services.call_service import save_end_of_call_report

        db = self._make_mock_db(None)  # No call found

        result = await save_end_of_call_report(
            db=db,
            vapi_call_id="nonexistent-call-id",
            transcript="some transcript",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_ended_reason_sets_status_and_outcome(self):
        """HOOK-03: ended_reason sets status='ended' and outcome."""
        from app.services.call_service import save_end_of_call_report

        call = self._make_mock_call(status="in-progress")
        db = self._make_mock_db(call)

        await save_end_of_call_report(
            db=db,
            vapi_call_id=VAPI_CALL_ID,
            ended_reason="customer-ended-call",
        )

        assert call.status == "ended"
        assert call.outcome == "customer-ended-call"

    @pytest.mark.asyncio
    async def test_duration_set_explicitly(self):
        """HOOK-03: Explicit duration is set directly."""
        from app.services.call_service import save_end_of_call_report

        call = self._make_mock_call()
        db = self._make_mock_db(call)

        await save_end_of_call_report(
            db=db,
            vapi_call_id=VAPI_CALL_ID,
            duration=180,
        )

        assert call.duration_seconds == 180

    @pytest.mark.asyncio
    async def test_duration_calculated_from_timestamps(self):
        """HOOK-03: Duration is auto-calculated from started_at/ended_at if not provided."""
        from app.services.call_service import save_end_of_call_report

        started = datetime(2026, 3, 8, 10, 0, 0, tzinfo=timezone.utc)
        ended = datetime(2026, 3, 8, 10, 3, 30, tzinfo=timezone.utc)

        call = self._make_mock_call(
            started_at=started,
            ended_at=ended,
            duration_seconds=None,
        )
        db = self._make_mock_db(call)

        await save_end_of_call_report(
            db=db,
            vapi_call_id=VAPI_CALL_ID,
        )

        # 3 minutes 30 seconds = 210 seconds
        assert call.duration_seconds == 210

    @pytest.mark.asyncio
    async def test_caller_intent_truncated_to_50_chars(self):
        """HOOK-05: caller_intent is truncated to 50 characters."""
        from app.services.call_service import save_end_of_call_report

        call = self._make_mock_call()
        db = self._make_mock_db(call)

        long_intent = "x" * 100
        await save_end_of_call_report(
            db=db,
            vapi_call_id=VAPI_CALL_ID,
            structured_data={"caller_intent": long_intent},
        )

        assert len(call.caller_intent) == 50

    @pytest.mark.asyncio
    async def test_caller_sentiment_truncated_to_20_chars(self):
        """HOOK-05: caller_sentiment is truncated to 20 characters."""
        from app.services.call_service import save_end_of_call_report

        call = self._make_mock_call()
        db = self._make_mock_db(call)

        long_sentiment = "y" * 50
        await save_end_of_call_report(
            db=db,
            vapi_call_id=VAPI_CALL_ID,
            structured_data={"caller_sentiment": long_sentiment},
        )

        assert len(call.caller_sentiment) == 20


# ===========================================================================
# Class 4: TestPracticeResolution (HOOK-04)
# ===========================================================================

class TestPracticeResolution:
    """Tests for resolve_practice_from_phone with mock DB session."""

    @pytest.mark.asyncio
    async def test_known_phone_returns_practice_id(self):
        """HOOK-04: Known phone number returns correct practice_id."""
        from app.services.call_service import resolve_practice_from_phone

        expected_id = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = expected_id

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await resolve_practice_from_phone(db, "+12678052214")
        assert result == expected_id

    @pytest.mark.asyncio
    async def test_unknown_phone_returns_none(self):
        """HOOK-04: Unknown phone number returns None."""
        from app.services.call_service import resolve_practice_from_phone

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await resolve_practice_from_phone(db, "+19999999999")
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_practice_id_from_existing_call(self):
        """HOOK-04: Practice resolved from existing call record by vapi_call_id."""
        from app.services.call_service import get_practice_id_from_vapi_call

        expected_id = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = expected_id

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await get_practice_id_from_vapi_call(db, "call_existing_123")
        assert result == expected_id

    @pytest.mark.asyncio
    async def test_resolve_practice_id_missing_call_returns_none(self):
        """HOOK-04: No call record found returns None."""
        from app.services.call_service import get_practice_id_from_vapi_call

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await get_practice_id_from_vapi_call(db, "call_nonexistent_456")
        assert result is None


# ===========================================================================
# Class 5: TestMalformedPayloads (HOOK-07)
# ===========================================================================

class TestMalformedPayloads:
    """Tests for error handling of bad webhook inputs."""

    @pytest_asyncio.fixture
    async def client(self):
        """Create an ASGI test client with dev-mode settings (no signature check)."""
        with patch("app.routes.webhooks.get_settings") as mock_gs:
            mock_gs.return_value = _mock_settings(secret="", app_env="development")

            from app.main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
                yield ac

    @pytest.mark.asyncio
    async def test_non_json_body_returns_400(self, client):
        """HOOK-07: Non-JSON body returns 400."""
        resp = await client.post(
            "/api/webhooks/vapi",
            content=b"this is not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_body_returns_400(self, client):
        """HOOK-07: Empty body returns 400."""
        resp = await client.post(
            "/api/webhooks/vapi",
            content=b"",
            headers={"Content-Type": "application/json"},
        )
        # FastAPI may return 400 or 422 for empty body
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_missing_message_field_returns_400(self, client):
        """HOOK-07: JSON body without 'message' field returns 400."""
        resp = await client.post(
            "/api/webhooks/vapi",
            json={"not_message": {"type": "test"}},
        )
        # Parsed as JSON but fails schema validation -> 400
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_type_field_returns_400(self, client):
        """HOOK-07: Message without 'type' field returns 400."""
        resp = await client.post(
            "/api/webhooks/vapi",
            json={"message": {"no_type": "test"}},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    @patch("app.routes.webhooks._resolve_practice_id", new_callable=AsyncMock, return_value=PRACTICE_ID)
    async def test_valid_structure_unknown_type_returns_200(self, mock_resolve, client):
        """HOOK-07: Valid structure with unknown message type returns 200 (graceful)."""
        body = _build_webhook_body("some-unknown-future-type")
        resp = await client.post("/api/webhooks/vapi", json=body)
        assert resp.status_code == 200


# ===========================================================================
# Class 6: TestConcurrentCalls (HOOK-08)
# ===========================================================================

class TestConcurrentCalls:
    """Tests for concurrent processing safety."""

    @pytest.mark.asyncio
    async def test_concurrent_calls_independent_processing(self):
        """HOOK-08: Two calls with different IDs to same practice process independently."""
        from app.services.call_service import save_end_of_call_report

        # Create two independent call mocks for the same practice
        call_a = MagicMock()
        call_a.id = uuid.uuid4()
        call_a.practice_id = PRACTICE_ID
        call_a.vapi_call_id = "call_aaa"
        call_a.transcription = None
        call_a.recording_url = None
        call_a.ai_summary = None
        call_a.vapi_cost = None
        call_a.structured_data = None
        call_a.caller_intent = None
        call_a.caller_sentiment = None
        call_a.language = "en"
        call_a.status = "in-progress"
        call_a.outcome = None
        call_a.call_metadata = None
        call_a.success_evaluation = None
        call_a.duration_seconds = None
        call_a.started_at = None
        call_a.ended_at = None

        call_b = MagicMock()
        call_b.id = uuid.uuid4()
        call_b.practice_id = PRACTICE_ID
        call_b.vapi_call_id = "call_bbb"
        call_b.transcription = None
        call_b.recording_url = None
        call_b.ai_summary = None
        call_b.vapi_cost = None
        call_b.structured_data = None
        call_b.caller_intent = None
        call_b.caller_sentiment = None
        call_b.language = "en"
        call_b.status = "in-progress"
        call_b.outcome = None
        call_b.call_metadata = None
        call_b.success_evaluation = None
        call_b.duration_seconds = None
        call_b.started_at = None
        call_b.ended_at = None

        # Create separate mock DB sessions for each call
        def make_db(call_obj, call_id):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = call_obj
            db = AsyncMock()
            db.execute.return_value = mock_result
            db.flush = AsyncMock()
            db.refresh = AsyncMock()
            return db

        db_a = make_db(call_a, "call_aaa")
        db_b = make_db(call_b, "call_bbb")

        # Run concurrently
        await asyncio.gather(
            save_end_of_call_report(
                db=db_a,
                vapi_call_id="call_aaa",
                transcript="Call A transcript",
                summary="Call A summary",
                cost=0.10,
            ),
            save_end_of_call_report(
                db=db_b,
                vapi_call_id="call_bbb",
                transcript="Call B transcript",
                summary="Call B summary",
                cost=0.20,
            ),
        )

        # Verify each call got its own data
        assert call_a.transcription == "Call A transcript"
        assert call_a.ai_summary == "Call A summary"
        assert call_a.vapi_cost == Decimal("0.10")

        assert call_b.transcription == "Call B transcript"
        assert call_b.ai_summary == "Call B summary"
        assert call_b.vapi_cost == Decimal("0.20")

    @pytest.mark.asyncio
    async def test_no_shared_mutable_state_between_calls(self):
        """HOOK-08: Verify no shared mutable state between concurrent call processing."""
        from app.services.call_service import save_end_of_call_report

        results = []

        async def process_call(call_id, intent, sentiment):
            call = MagicMock()
            call.id = uuid.uuid4()
            call.practice_id = PRACTICE_ID
            call.vapi_call_id = call_id
            call.transcription = None
            call.recording_url = None
            call.ai_summary = None
            call.vapi_cost = None
            call.structured_data = None
            call.caller_intent = None
            call.caller_sentiment = None
            call.language = "en"
            call.status = "in-progress"
            call.outcome = None
            call.call_metadata = None
            call.success_evaluation = None
            call.duration_seconds = None
            call.started_at = None
            call.ended_at = None

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = call
            db = AsyncMock()
            db.execute.return_value = mock_result
            db.flush = AsyncMock()
            db.refresh = AsyncMock()

            await save_end_of_call_report(
                db=db,
                vapi_call_id=call_id,
                structured_data={
                    "caller_intent": intent,
                    "caller_sentiment": sentiment,
                    "language": "english",
                },
            )
            results.append((call.caller_intent, call.caller_sentiment, call.language))

        # Run 5 concurrent calls with different data
        await asyncio.gather(
            process_call("c1", "book", "positive"),
            process_call("c2", "cancel", "negative"),
            process_call("c3", "reschedule", "neutral"),
            process_call("c4", "insurance", "frustrated"),
            process_call("c5", "billing", "positive"),
        )

        # Each result should be independent
        assert len(results) == 5
        intents = {r[0] for r in results}
        assert intents == {"book", "cancel", "reschedule", "insurance", "billing"}
        sentiments = {r[1] for r in results}
        assert sentiments == {"positive", "negative", "neutral", "frustrated"}
        # All languages should be "en" (mapped from "english")
        assert all(r[2] == "en" for r in results)


# ===========================================================================
# Bonus: TestHelperFunctions
# ===========================================================================

class TestHelperFunctions:
    """Tests for webhook helper functions (parse_params, _safe_get)."""

    def test_parse_params_from_json_string(self):
        """parse_params correctly parses a JSON string."""
        from app.routes.webhooks import parse_params
        result = parse_params('{"name": "John", "phone": "+1234"}')
        assert result == {"name": "John", "phone": "+1234"}

    def test_parse_params_from_dict(self):
        """parse_params returns dict as-is."""
        from app.routes.webhooks import parse_params
        result = parse_params({"name": "John"})
        assert result == {"name": "John"}

    def test_parse_params_invalid_json_returns_empty(self):
        """parse_params returns empty dict for invalid JSON."""
        from app.routes.webhooks import parse_params
        result = parse_params("not json at all")
        assert result == {}

    def test_parse_params_none_returns_empty(self):
        """parse_params returns empty dict for non-string/non-dict input."""
        from app.routes.webhooks import parse_params
        result = parse_params(None)
        assert result == {}

    def test_safe_get_nested_keys(self):
        """_safe_get traverses nested dicts correctly."""
        from app.routes.webhooks import _safe_get
        data = {"a": {"b": {"c": "value"}}}
        assert _safe_get(data, "a", "b", "c") == "value"

    def test_safe_get_missing_key_returns_default(self):
        """_safe_get returns default for missing keys."""
        from app.routes.webhooks import _safe_get
        data = {"a": {"b": 1}}
        assert _safe_get(data, "a", "x", default="fallback") == "fallback"

    def test_safe_get_none_intermediate(self):
        """_safe_get returns default when intermediate value is None."""
        from app.routes.webhooks import _safe_get
        data = {"a": None}
        assert _safe_get(data, "a", "b", default="default") == "default"
