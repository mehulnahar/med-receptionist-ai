"""
Tests for Vapi Config Sync (Phase 4: VAPI-06, VAPI-07, VAPI-08).

Pure unit tests -- NO real Vapi API calls, all HTTP interactions mocked.
Tests cover: positive sync payloads, error handling, and concurrent safety.

Covers:
  VAPI-06: Config changes produce correct Vapi API PATCH payloads
  VAPI-07: Error scenarios (auth, rate limit, timeout, network) return descriptive errors
  VAPI-08: Concurrent sync calls complete independently without corruption
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.vapi_service import sync_assistant_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ASSISTANT_ID = "asst_test_123"
FAKE_API_KEY = "test-vapi-key-abc123"
VAPI_BASE = "https://api.vapi.ai"

# Default assistant config returned by GET (simulates current Vapi state)
DEFAULT_ASSISTANT_CONFIG = {
    "id": ASSISTANT_ID,
    "firstMessage": "Hello! Thank you for calling.",
    "model": {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "messages": [{"role": "system", "content": "You are a medical receptionist."}],
        "tools": [
            {
                "type": "transferCall",
                "destinations": [{"type": "number", "number": "+12125551234"}],
                "function": {
                    "name": "transferCall",
                    "description": "Transfer the call to staff.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    },
    "voice": {"provider": "11labs", "voiceId": "voice_abc"},
}


def _make_request(method: str = "GET", url: str = "") -> httpx.Request:
    """Create a minimal httpx.Request for Response construction."""
    return httpx.Request(method, url or f"{VAPI_BASE}/assistant/{ASSISTANT_ID}")


def make_mock_client(
    get_response=None,
    patch_response=None,
    get_side_effect=None,
    patch_side_effect=None,
):
    """Create a mock httpx.AsyncClient with configurable get/patch responses."""
    mock_client = AsyncMock()

    # Default GET response: current assistant config
    if get_response is None:
        get_response = httpx.Response(
            200,
            json=DEFAULT_ASSISTANT_CONFIG,
            request=_make_request("GET"),
        )
    # Default PATCH response: success
    if patch_response is None:
        patch_response = httpx.Response(
            200,
            json={"id": ASSISTANT_ID},
            request=_make_request("PATCH"),
        )

    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    if get_side_effect:
        mock_client.get = AsyncMock(side_effect=get_side_effect)
    else:
        mock_client.get = AsyncMock(return_value=get_response)

    if patch_side_effect:
        mock_client.patch = AsyncMock(side_effect=patch_side_effect)
    else:
        mock_client.patch = AsyncMock(return_value=patch_response)

    return mock_client


# ===========================================================================
# Class 1: TestVapiSyncPositive (VAPI-06)
# ===========================================================================


class TestVapiSyncPositive:
    """Tests that config changes produce correct Vapi API payloads."""

    @pytest.mark.asyncio
    @patch("app.services.vapi_service.httpx.AsyncClient")
    async def test_sync_system_prompt(self, mock_client_cls):
        """VAPI-06: Changing system_prompt sends correct PATCH payload with model.messages."""
        client = make_mock_client()
        mock_client_cls.return_value = client

        result = await sync_assistant_config(
            ASSISTANT_ID,
            FAKE_API_KEY,
            system_prompt="You are Dr. Smith's receptionist.",
        )

        assert result == {"success": True, "error": None}

        # Verify PATCH was called
        client.patch.assert_awaited_once()
        patch_call = client.patch.call_args
        payload = patch_call.kwargs.get("json") or patch_call[1].get("json")

        # Verify system prompt in payload
        assert "model" in payload
        assert payload["model"]["messages"] == [
            {"role": "system", "content": "You are Dr. Smith's receptionist."}
        ]
        # Verify existing tools preserved
        assert "tools" in payload["model"]
        tool_types = [t["type"] for t in payload["model"]["tools"]]
        assert "transferCall" in tool_types

    @pytest.mark.asyncio
    @patch("app.services.vapi_service.httpx.AsyncClient")
    async def test_sync_first_message(self, mock_client_cls):
        """VAPI-06: Changing first_message sends correct PATCH payload."""
        client = make_mock_client()
        mock_client_cls.return_value = client

        result = await sync_assistant_config(
            ASSISTANT_ID,
            FAKE_API_KEY,
            first_message="Welcome to our office!",
        )

        assert result == {"success": True, "error": None}

        client.patch.assert_awaited_once()
        patch_call = client.patch.call_args
        payload = patch_call.kwargs.get("json") or patch_call[1].get("json")

        assert payload["firstMessage"] == "Welcome to our office!"

    @pytest.mark.asyncio
    @patch("app.services.vapi_service.httpx.AsyncClient")
    async def test_sync_voice_settings(self, mock_client_cls):
        """VAPI-06: Changing voice_provider and voice_id sends correct PATCH payload."""
        client = make_mock_client()
        mock_client_cls.return_value = client

        result = await sync_assistant_config(
            ASSISTANT_ID,
            FAKE_API_KEY,
            voice_provider="deepgram",
            voice_id="nova-2",
        )

        assert result == {"success": True, "error": None}

        client.patch.assert_awaited_once()
        patch_call = client.patch.call_args
        payload = patch_call.kwargs.get("json") or patch_call[1].get("json")

        assert payload["voice"]["provider"] == "deepgram"
        assert payload["voice"]["voiceId"] == "nova-2"

    @pytest.mark.asyncio
    @patch("app.services.vapi_service.httpx.AsyncClient")
    async def test_sync_model_settings(self, mock_client_cls):
        """VAPI-06: Changing model_provider and model_name sends correct PATCH payload."""
        client = make_mock_client()
        mock_client_cls.return_value = client

        result = await sync_assistant_config(
            ASSISTANT_ID,
            FAKE_API_KEY,
            model_provider="anthropic",
            model_name="claude-sonnet-4-5-20250929",
        )

        assert result == {"success": True, "error": None}

        client.patch.assert_awaited_once()
        patch_call = client.patch.call_args
        payload = patch_call.kwargs.get("json") or patch_call[1].get("json")

        assert payload["model"]["provider"] == "anthropic"
        assert payload["model"]["model"] == "claude-sonnet-4-5-20250929"
        # Verify existing tools preserved
        assert "tools" in payload["model"]
        tool_types = [t["type"] for t in payload["model"]["tools"]]
        assert "transferCall" in tool_types

    @pytest.mark.asyncio
    @patch("app.services.vapi_service.httpx.AsyncClient")
    async def test_sync_multiple_fields(self, mock_client_cls):
        """VAPI-06: Syncing multiple fields at once produces a single PATCH with all changes."""
        client = make_mock_client()
        mock_client_cls.return_value = client

        result = await sync_assistant_config(
            ASSISTANT_ID,
            FAKE_API_KEY,
            system_prompt="New prompt here",
            first_message="Hi there!",
            voice_id="voice_new_xyz",
        )

        assert result == {"success": True, "error": None}

        client.patch.assert_awaited_once()
        patch_call = client.patch.call_args
        payload = patch_call.kwargs.get("json") or patch_call[1].get("json")

        # All three field groups present in single PATCH
        assert payload["model"]["messages"] == [
            {"role": "system", "content": "New prompt here"}
        ]
        assert payload["firstMessage"] == "Hi there!"
        assert payload["voice"]["voiceId"] == "voice_new_xyz"

    @pytest.mark.asyncio
    @patch("app.services.vapi_service.httpx.AsyncClient")
    async def test_sync_no_fields_is_noop(self, mock_client_cls):
        """VAPI-06: Calling with no optional fields is a no-op (no HTTP requests made)."""
        client = make_mock_client()
        mock_client_cls.return_value = client

        result = await sync_assistant_config(
            ASSISTANT_ID,
            FAKE_API_KEY,
        )

        assert result == {"success": True, "error": None}

        # No GET or PATCH should have been called
        client.get.assert_not_awaited()
        client.patch.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.services.vapi_service.httpx.AsyncClient")
    async def test_sync_preserves_existing_tools(self, mock_client_cls):
        """VAPI-06: GET-merge-PATCH preserves existing tools when only changing prompt."""
        client = make_mock_client()
        mock_client_cls.return_value = client

        result = await sync_assistant_config(
            ASSISTANT_ID,
            FAKE_API_KEY,
            system_prompt="Updated receptionist prompt",
        )

        assert result == {"success": True, "error": None}

        patch_call = client.patch.call_args
        payload = patch_call.kwargs.get("json") or patch_call[1].get("json")

        # Tools from the GET response must still be in the PATCH payload
        assert "tools" in payload["model"]
        assert len(payload["model"]["tools"]) == 1
        assert payload["model"]["tools"][0]["type"] == "transferCall"
        assert payload["model"]["tools"][0]["destinations"][0]["number"] == "+12125551234"

    @pytest.mark.asyncio
    @patch("app.services.vapi_service.httpx.AsyncClient")
    async def test_sync_returns_success(self, mock_client_cls):
        """VAPI-06: Successful sync returns {success: True, error: None}."""
        client = make_mock_client()
        mock_client_cls.return_value = client

        result = await sync_assistant_config(
            ASSISTANT_ID,
            FAKE_API_KEY,
            first_message="Greetings!",
        )

        assert result["success"] is True
        assert result["error"] is None


# ===========================================================================
# Class 2: TestVapiSyncErrors (VAPI-07)
# ===========================================================================


class TestVapiSyncErrors:
    """Tests for error handling in sync_assistant_config."""

    @pytest.mark.asyncio
    @patch("app.services.vapi_service.httpx.AsyncClient")
    async def test_sync_invalid_api_key_401(self, mock_client_cls):
        """VAPI-07: 401 response produces 'Invalid Vapi API key' error."""
        error_response = httpx.Response(
            401,
            json={"message": "Unauthorized"},
            request=_make_request("PATCH"),
        )
        client = make_mock_client(
            patch_response=error_response,
        )
        # Make PATCH raise HTTPStatusError (like raise_for_status does)
        client.patch = AsyncMock(return_value=error_response)
        mock_client_cls.return_value = client

        # We need to simulate raise_for_status() being called.
        # The real code calls patch_resp.raise_for_status(), so we need the
        # response to actually raise. Use a side effect instead.
        async def patch_raises(*args, **kwargs):
            resp = httpx.Response(
                401,
                json={"message": "Unauthorized"},
                request=_make_request("PATCH"),
            )
            resp.raise_for_status()
            return resp  # won't reach here

        client.patch = AsyncMock(side_effect=patch_raises)

        result = await sync_assistant_config(
            ASSISTANT_ID,
            FAKE_API_KEY,
            system_prompt="test",
        )

        assert result["success"] is False
        assert "Invalid Vapi API key" in result["error"]

    @pytest.mark.asyncio
    @patch("app.services.vapi_service.httpx.AsyncClient")
    async def test_sync_rate_limited_429(self, mock_client_cls):
        """VAPI-07: 429 response produces 'rate limit' error."""

        async def patch_raises(*args, **kwargs):
            resp = httpx.Response(
                429,
                json={"message": "Too Many Requests"},
                request=_make_request("PATCH"),
            )
            resp.raise_for_status()

        client = make_mock_client(patch_side_effect=patch_raises)
        mock_client_cls.return_value = client

        result = await sync_assistant_config(
            ASSISTANT_ID,
            FAKE_API_KEY,
            system_prompt="test",
        )

        assert result["success"] is False
        assert "rate limit" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("app.services.vapi_service.httpx.AsyncClient")
    async def test_sync_vapi_server_error_500(self, mock_client_cls):
        """VAPI-07: 500 response produces 'temporarily unavailable' error."""

        async def patch_raises(*args, **kwargs):
            resp = httpx.Response(
                500,
                json={"message": "Internal Server Error"},
                request=_make_request("PATCH"),
            )
            resp.raise_for_status()

        client = make_mock_client(patch_side_effect=patch_raises)
        mock_client_cls.return_value = client

        result = await sync_assistant_config(
            ASSISTANT_ID,
            FAKE_API_KEY,
            system_prompt="test",
        )

        assert result["success"] is False
        assert "temporarily unavailable" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("app.services.vapi_service.httpx.AsyncClient")
    async def test_sync_timeout(self, mock_client_cls):
        """VAPI-07: Timeout raises descriptive 'timed out' error."""

        async def patch_timeout(*args, **kwargs):
            raise httpx.TimeoutException("Connection timed out")

        client = make_mock_client(patch_side_effect=patch_timeout)
        mock_client_cls.return_value = client

        result = await sync_assistant_config(
            ASSISTANT_ID,
            FAKE_API_KEY,
            system_prompt="test",
        )

        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_sync_missing_api_key(self):
        """VAPI-07: Empty API key (no per-practice, no global) returns config error."""
        with patch("app.services.vapi_service.settings") as mock_settings:
            mock_settings.VAPI_API_KEY = ""  # No global fallback

            result = await sync_assistant_config(
                ASSISTANT_ID,
                vapi_api_key="",  # No per-practice key either
                system_prompt="test",
            )

        assert result["success"] is False
        assert "not configured" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_sync_missing_assistant_id(self):
        """VAPI-07: Empty assistant_id returns config error."""
        result = await sync_assistant_config(
            "",  # empty assistant ID
            FAKE_API_KEY,
            system_prompt="test",
        )

        assert result["success"] is False
        assert "not configured" in result["error"].lower()

    @pytest.mark.asyncio
    @patch("app.services.vapi_service.httpx.AsyncClient")
    async def test_sync_get_fails(self, mock_client_cls):
        """VAPI-07: GET failure (500) prevents PATCH and returns error."""

        async def get_raises(*args, **kwargs):
            resp = httpx.Response(
                500,
                json={"message": "Internal Server Error"},
                request=_make_request("GET"),
            )
            resp.raise_for_status()

        client = make_mock_client(get_side_effect=get_raises)
        mock_client_cls.return_value = client

        result = await sync_assistant_config(
            ASSISTANT_ID,
            FAKE_API_KEY,
            system_prompt="test",
        )

        assert result["success"] is False
        # PATCH should never have been called since GET failed
        client.patch.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.services.vapi_service.httpx.AsyncClient")
    async def test_sync_network_error(self, mock_client_cls):
        """VAPI-07: Network/connection error produces descriptive error."""

        async def patch_connect_error(*args, **kwargs):
            raise httpx.ConnectError("Connection refused")

        client = make_mock_client(patch_side_effect=patch_connect_error)
        mock_client_cls.return_value = client

        result = await sync_assistant_config(
            ASSISTANT_ID,
            FAKE_API_KEY,
            system_prompt="test",
        )

        assert result["success"] is False
        assert result["error"] is not None
        assert len(result["error"]) > 0


# ===========================================================================
# Class 3: TestVapiSyncConcurrency (VAPI-08)
# ===========================================================================


class TestVapiSyncConcurrency:
    """Tests for concurrent sync safety."""

    @pytest.mark.asyncio
    @patch("app.services.vapi_service.httpx.AsyncClient")
    async def test_concurrent_syncs_both_complete(self, mock_client_cls):
        """VAPI-08: Two concurrent sync calls both complete successfully."""
        # Each call gets its own mock client instance
        client_a = make_mock_client()
        client_b = make_mock_client()
        mock_client_cls.side_effect = [client_a, client_b]

        result_a, result_b = await asyncio.gather(
            sync_assistant_config(
                ASSISTANT_ID,
                FAKE_API_KEY,
                system_prompt="Prompt A",
            ),
            sync_assistant_config(
                ASSISTANT_ID,
                FAKE_API_KEY,
                voice_id="voice_b",
            ),
        )

        assert result_a == {"success": True, "error": None}
        assert result_b == {"success": True, "error": None}

        # Both made their PATCH calls
        client_a.patch.assert_awaited_once()
        client_b.patch.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.services.vapi_service.httpx.AsyncClient")
    async def test_concurrent_syncs_independent_payloads(self, mock_client_cls):
        """VAPI-08: Concurrent syncs produce independent payloads (no cross-contamination)."""
        client_a = make_mock_client()
        client_b = make_mock_client()
        mock_client_cls.side_effect = [client_a, client_b]

        await asyncio.gather(
            sync_assistant_config(
                ASSISTANT_ID,
                FAKE_API_KEY,
                system_prompt="Prompt for call A",
            ),
            sync_assistant_config(
                ASSISTANT_ID,
                FAKE_API_KEY,
                voice_id="voice_for_call_b",
            ),
        )

        # Extract payloads
        payload_a = client_a.patch.call_args.kwargs.get("json") or client_a.patch.call_args[1].get("json")
        payload_b = client_b.patch.call_args.kwargs.get("json") or client_b.patch.call_args[1].get("json")

        # Call A should have model with prompt, NOT voice changes
        assert "model" in payload_a
        assert payload_a["model"]["messages"] == [
            {"role": "system", "content": "Prompt for call A"}
        ]
        assert "voice" not in payload_a  # No voice change in call A

        # Call B should have voice changes, NOT model/prompt changes
        assert "voice" in payload_b
        assert payload_b["voice"]["voiceId"] == "voice_for_call_b"
        assert "model" not in payload_b  # No model change in call B
