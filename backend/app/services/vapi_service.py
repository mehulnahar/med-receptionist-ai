"""
Vapi Assistant Management Service.

Handles updates to the Vapi assistant configuration, including:
- Syncing transfer number when practice config changes
- Future: syncing system prompt, voice settings, etc.
"""

import json
import logging
import urllib.request
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def update_assistant_transfer_number(
    assistant_id: str,
    transfer_number: Optional[str],
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

    try:
        # First, GET the current assistant config
        req = urllib.request.Request(
            f"https://api.vapi.ai/assistant/{assistant_id}",
            headers={
                "Authorization": f"Bearer {settings.VAPI_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            current = json.loads(resp.read().decode("utf-8"))

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
                        "message": "I'm transferring you to our office staff now. Please hold for just a moment.",
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

        data = json.dumps(patch).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.vapi.ai/assistant/{assistant_id}",
            data=data,
            method="PATCH",
            headers={
                "Authorization": f"Bearer {settings.VAPI_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))

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
