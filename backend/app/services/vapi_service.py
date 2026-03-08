"""
Vapi Assistant Management Service.

Handles updates to the Vapi assistant configuration, including:
- Syncing transfer number when practice config changes
- Syncing system prompt, voice, model, and greeting via sync_assistant_config
"""

import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_VAPI_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


async def update_assistant_transfer_number(
    assistant_id: str,
    transfer_number: Optional[str],
    transfer_message: Optional[str] = None,
) -> bool:
    """
    Update the transferCall tool on a Vapi assistant with a new phone number.

    If transfer_number is provided, replaces the transfer_to_staff function tool
    with a native transferCall tool pointing to that number.

    If transfer_number is None/empty, removes the transferCall tool entirely.

    Returns True on success, False on failure.
    """
    if not settings.VAPI_API_KEY:
        logger.warning("update_assistant_transfer_number: VAPI_API_KEY not set")
        return False

    if not assistant_id:
        logger.warning("update_assistant_transfer_number: no assistant_id provided")
        return False

    headers = {
        "Authorization": f"Bearer {settings.VAPI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_VAPI_TIMEOUT) as client:
            # First, GET the current assistant config
            resp = await client.get(
                f"https://api.vapi.ai/assistant/{assistant_id}",
                headers=headers,
            )
            resp.raise_for_status()
            current = resp.json()

            model = current.get("model", {})
            tools = model.get("tools", [])

            # Remove any existing transfer_to_staff or transferCall tools
            filtered_tools = [
                t for t in tools
                if not (
                    (t.get("type") == "function" and
                     t.get("function", {}).get("name") == "transfer_to_staff")
                    or t.get("type") == "transferCall"
                )
            ]

            # Add native transferCall tool if number is provided
            if transfer_number and transfer_number.strip():
                transfer_tool = {
                    "type": "transferCall",
                    "destinations": [
                        {
                            "type": "number",
                            "number": transfer_number.strip(),
                            "message": transfer_message or "I'm transferring you to our office staff now. Please hold for just a moment.",
                        }
                    ],
                    "function": {
                        "name": "transferCall",
                        "description": "Transfer the call to a human staff member at the office. Use this when: the caller asks for a real person, has billing questions, speaks Greek, or you cannot help them after multiple attempts.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "destination": {
                                    "type": "string",
                                    "enum": [transfer_number.strip()],
                                    "description": "The phone number to transfer to",
                                }
                            },
                            "required": ["destination"],
                        },
                    },
                }
                filtered_tools.append(transfer_tool)
                logger.info(
                    "update_assistant_transfer_number: adding transferCall to %s → %s",
                    assistant_id, transfer_number,
                )
            else:
                logger.info(
                    "update_assistant_transfer_number: removing transfer tool from %s (no number)",
                    assistant_id,
                )

            # PATCH the assistant with updated tools
            patch = {
                "model": {
                    **model,
                    "tools": filtered_tools,
                }
            }

            resp = await client.patch(
                f"https://api.vapi.ai/assistant/{assistant_id}",
                json=patch,
                headers=headers,
            )
            resp.raise_for_status()
            result = resp.json()

        updated_tools = result.get("model", {}).get("tools", [])
        tool_names = [
            t.get("function", {}).get("name", t.get("type", "?"))
            for t in updated_tools
        ]
        logger.info(
            "update_assistant_transfer_number: success. Tools: %s",
            tool_names,
        )
        return True

    except Exception as e:
        logger.exception(
            "update_assistant_transfer_number: failed for assistant %s: %s",
            assistant_id, e,
        )
        return False


async def sync_assistant_config(
    assistant_id: str,
    vapi_api_key: str | None = None,
    *,
    system_prompt: str | None = None,
    first_message: str | None = None,
    model_provider: str | None = None,
    model_name: str | None = None,
    voice_provider: str | None = None,
    voice_id: str | None = None,
) -> dict:
    """
    Sync practice config fields to the Vapi assistant via GET-merge-PATCH.

    Accepts per-practice vapi_api_key, falling back to the global VAPI_API_KEY.
    Only fields explicitly provided (not None) are synced.

    Returns {"success": bool, "error": str | None}.
    """
    api_key = vapi_api_key or settings.VAPI_API_KEY
    if not api_key or not assistant_id:
        return {
            "success": False,
            "error": "Vapi API key or assistant ID not configured",
        }

    # Check if any field was actually provided
    has_model_fields = any(v is not None for v in (system_prompt, model_provider, model_name))
    has_voice_fields = any(v is not None for v in (voice_provider, voice_id))
    has_first_message = first_message is not None

    if not has_model_fields and not has_voice_fields and not has_first_message:
        return {"success": True, "error": None}  # no-op

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_VAPI_TIMEOUT) as client:
            # GET current assistant config to merge changes safely
            get_resp = await client.get(
                f"https://api.vapi.ai/assistant/{assistant_id}",
                headers=headers,
            )
            get_resp.raise_for_status()
            current = get_resp.json()

            patch_payload: dict = {}

            # --- Model fields (prompt, provider, model name) ---
            if has_model_fields:
                current_model = current.get("model", {})
                merged_model = {**current_model}

                if system_prompt is not None:
                    merged_model["messages"] = [
                        {"role": "system", "content": system_prompt}
                    ]
                if model_provider is not None:
                    merged_model["provider"] = model_provider
                if model_name is not None:
                    merged_model["model"] = model_name

                patch_payload["model"] = merged_model

            # --- Voice fields ---
            if has_voice_fields:
                current_voice = current.get("voice", {})
                merged_voice = {**current_voice}

                if voice_provider is not None:
                    merged_voice["provider"] = voice_provider
                if voice_id is not None:
                    merged_voice["voiceId"] = voice_id

                patch_payload["voice"] = merged_voice

            # --- First message ---
            if has_first_message:
                patch_payload["firstMessage"] = first_message

            # PATCH the assistant with merged payload
            patch_resp = await client.patch(
                f"https://api.vapi.ai/assistant/{assistant_id}",
                json=patch_payload,
                headers=headers,
            )
            patch_resp.raise_for_status()

        logger.info(
            "sync_assistant_config: success for assistant %s (fields: %s)",
            assistant_id, list(patch_payload.keys()),
        )
        return {"success": True, "error": None}

    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code
        # Try to extract error message from Vapi response body
        try:
            body = e.response.json()
            detail = body.get("message", body.get("error", str(body)))
        except Exception:
            detail = e.response.text[:200] if e.response.text else str(e)

        if status_code in (401, 403):
            msg = "Invalid Vapi API key"
        elif status_code == 429:
            msg = "Vapi rate limit exceeded, please try again shortly"
        elif status_code >= 500:
            msg = "Vapi service temporarily unavailable"
        else:
            msg = f"Vapi API error ({status_code}): {detail}"

        logger.warning(
            "sync_assistant_config: HTTP %s for assistant %s: %s",
            status_code, assistant_id, msg,
        )
        return {"success": False, "error": msg}

    except httpx.TimeoutException:
        logger.warning(
            "sync_assistant_config: timeout for assistant %s", assistant_id,
        )
        return {"success": False, "error": "Vapi API request timed out"}

    except Exception as e:
        logger.exception(
            "sync_assistant_config: unexpected error for assistant %s: %s",
            assistant_id, e,
        )
        return {"success": False, "error": str(e)}
