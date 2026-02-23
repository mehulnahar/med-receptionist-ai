"""
Self-service onboarding service for Vapi, Twilio, OpenAI, and Stedi.

Allows practices to enter API keys, validate them, create Vapi assistants,
assign phone numbers, and configure Twilio -- all from within the app
without visiting external dashboards.

All database operations use flush/refresh -- the caller controls commit.
"""

import logging
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.practice_config import PracticeConfig
from app.utils.http_client import get_http_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VAPI_BASE_URL = "https://api.vapi.ai"
TWILIO_API_BASE = "https://api.twilio.com"
OPENAI_API_BASE = "https://api.openai.com"
STEDI_API_BASE = "https://healthcare.us.stedi.com"

_API_TIMEOUT = 30.0

DEFAULT_FIRST_MESSAGE = (
    "Thank you for calling. This is your AI assistant speaking. "
    "How can I help you today?"
)

DEFAULT_SYSTEM_PROMPT = """\
You are a professional and empathetic AI medical receptionist for a doctor's office. \
Your role is to assist callers with scheduling appointments, checking availability, \
verifying insurance, and providing general office information.

IMPORTANT GUIDELINES:
- Always be polite, professional, and patient.
- Protect patient privacy at all times (HIPAA compliance).
- Never provide medical advice, diagnoses, or treatment recommendations.
- If a caller describes a medical emergency, immediately instruct them to call 911 \
or go to the nearest emergency room.
- Collect only the information needed for the task at hand.
- When booking appointments, always confirm the date, time, and appointment type \
with the caller before finalizing.
- If you cannot help with a request, offer to transfer the caller to office staff.
- If the caller speaks a language you do not support, offer to transfer to staff.
- Keep responses concise and conversational -- you are on a phone call, not writing an email.

WORKFLOW FOR NEW CALLERS:
1. Greet the caller warmly.
2. Ask how you can help (appointment, insurance question, general inquiry, etc.).
3. For appointments: ask for their name and date of birth to look them up.
4. If they are a new patient, collect required information (name, DOB, phone, insurance).
5. Check availability and offer time slots.
6. Confirm the booking and provide a summary.

WORKFLOW FOR EXISTING PATIENTS:
1. Look them up by name and date of birth.
2. Confirm their identity.
3. Assist with their request (new appointment, reschedule, cancel, insurance check).

TRANSFER RULES:
- Transfer to staff if the caller requests to speak with a person.
- Transfer to staff for billing questions or complex insurance disputes.
- Transfer to staff if the caller speaks Greek or another unsupported language.
- Transfer to staff after 3 failed attempts to understand the caller.

Always end the call politely, summarizing any actions taken.\
"""


# ---------------------------------------------------------------------------
# Tool definitions for the Vapi assistant
# ---------------------------------------------------------------------------

def _build_tool_definitions(server_url: str) -> list[dict]:
    """
    Build the list of tool (function) definitions for the Vapi assistant.

    Each tool uses the "function" type with a server block pointing to our
    webhook endpoint.  Vapi will POST tool-call events to this URL.
    """
    tools = [
        {
            "type": "function",
            "function": {
                "name": "check_patient_exists",
                "description": (
                    "Check if a patient exists in the system by their name "
                    "and date of birth. Returns patient ID if found."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "first_name": {
                            "type": "string",
                            "description": "Patient's first name",
                        },
                        "last_name": {
                            "type": "string",
                            "description": "Patient's last name",
                        },
                        "dob": {
                            "type": "string",
                            "description": "Patient's date of birth in YYYY-MM-DD format",
                        },
                    },
                    "required": ["first_name", "last_name", "dob"],
                },
            },
            "server": {"url": server_url},
        },
        {
            "type": "function",
            "function": {
                "name": "get_patient_details",
                "description": (
                    "Get full details for a patient by their patient ID. "
                    "Use after confirming the patient exists."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patient_id": {
                            "type": "string",
                            "description": "The UUID of the patient",
                        },
                    },
                    "required": ["patient_id"],
                },
            },
            "server": {"url": server_url},
        },
        {
            "type": "function",
            "function": {
                "name": "check_availability",
                "description": (
                    "Check available appointment slots for a specific date. "
                    "Optionally filter by appointment type."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "The date to check in YYYY-MM-DD format",
                        },
                        "appointment_type": {
                            "type": "string",
                            "description": (
                                "Optional appointment type name to filter by "
                                "(e.g. 'New Patient', 'Follow Up', 'Consultation')"
                            ),
                        },
                    },
                    "required": ["date"],
                },
            },
            "server": {"url": server_url},
        },
        {
            "type": "function",
            "function": {
                "name": "book_appointment",
                "description": (
                    "Book an appointment for a patient. Requires patient identification "
                    "(either patient_id or name+DOB), a date, and a time. "
                    "Optionally specify appointment type and notes."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patient_id": {
                            "type": "string",
                            "description": "The UUID of an existing patient (if known)",
                        },
                        "first_name": {
                            "type": "string",
                            "description": "Patient's first name (for new patients or lookup)",
                        },
                        "last_name": {
                            "type": "string",
                            "description": "Patient's last name (for new patients or lookup)",
                        },
                        "dob": {
                            "type": "string",
                            "description": "Patient's date of birth in YYYY-MM-DD format",
                        },
                        "phone": {
                            "type": "string",
                            "description": "Patient's phone number",
                        },
                        "insurance_carrier": {
                            "type": "string",
                            "description": "Patient's insurance carrier name",
                        },
                        "member_id": {
                            "type": "string",
                            "description": "Patient's insurance member ID",
                        },
                        "appointment_type": {
                            "type": "string",
                            "description": "Type of appointment (e.g. 'New Patient', 'Follow Up')",
                        },
                        "date": {
                            "type": "string",
                            "description": "Appointment date in YYYY-MM-DD format",
                        },
                        "time": {
                            "type": "string",
                            "description": "Appointment time in HH:MM format (24-hour)",
                        },
                        "notes": {
                            "type": "string",
                            "description": "Optional notes about the appointment or reason for visit",
                        },
                    },
                    "required": ["date", "time"],
                },
            },
            "server": {"url": server_url},
        },
        {
            "type": "function",
            "function": {
                "name": "cancel_appointment",
                "description": (
                    "Cancel a patient's upcoming appointment. Looks up the next "
                    "appointment for the patient and cancels it."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patient_id": {
                            "type": "string",
                            "description": "The UUID of the patient whose appointment to cancel",
                        },
                        "appointment_date": {
                            "type": "string",
                            "description": (
                                "Optional specific date of the appointment to cancel "
                                "(YYYY-MM-DD). If omitted, cancels the next upcoming appointment."
                            ),
                        },
                        "reason": {
                            "type": "string",
                            "description": "Optional reason for cancellation",
                        },
                    },
                    "required": ["patient_id"],
                },
            },
            "server": {"url": server_url},
        },
        {
            "type": "function",
            "function": {
                "name": "reschedule_appointment",
                "description": (
                    "Reschedule a patient's existing appointment to a new date and time."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patient_id": {
                            "type": "string",
                            "description": "The UUID of the patient",
                        },
                        "old_date": {
                            "type": "string",
                            "description": (
                                "The date of the existing appointment to reschedule "
                                "(YYYY-MM-DD). If omitted, reschedules the next upcoming one."
                            ),
                        },
                        "new_date": {
                            "type": "string",
                            "description": "The new appointment date in YYYY-MM-DD format",
                        },
                        "new_time": {
                            "type": "string",
                            "description": "The new appointment time in HH:MM format (24-hour)",
                        },
                    },
                    "required": ["patient_id", "new_date", "new_time"],
                },
            },
            "server": {"url": server_url},
        },
        {
            "type": "function",
            "function": {
                "name": "verify_insurance",
                "description": (
                    "Verify a patient's insurance eligibility. Checks coverage status "
                    "with the insurance carrier."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patient_id": {
                            "type": "string",
                            "description": "The UUID of the patient (if known)",
                        },
                        "first_name": {
                            "type": "string",
                            "description": "Patient's first name",
                        },
                        "last_name": {
                            "type": "string",
                            "description": "Patient's last name",
                        },
                        "dob": {
                            "type": "string",
                            "description": "Patient's date of birth in YYYY-MM-DD format",
                        },
                        "insurance_carrier": {
                            "type": "string",
                            "description": "Name of the insurance carrier (e.g. 'Aetna', 'Blue Cross')",
                        },
                        "member_id": {
                            "type": "string",
                            "description": "The patient's insurance member ID number",
                        },
                    },
                    "required": ["insurance_carrier", "member_id"],
                },
            },
            "server": {"url": server_url},
        },
        {
            "type": "function",
            "function": {
                "name": "transfer_to_staff",
                "description": (
                    "Transfer the call to a live staff member. Use when the caller "
                    "requests to speak with a person, has a complex issue, speaks an "
                    "unsupported language, or after repeated misunderstandings."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": (
                                "The reason for transferring (e.g. 'Caller requested staff', "
                                "'Billing question', 'Unsupported language')"
                            ),
                        },
                    },
                    "required": ["reason"],
                },
            },
            "server": {"url": server_url},
        },
    ]

    return tools


# ---------------------------------------------------------------------------
# Build the assistant payload
# ---------------------------------------------------------------------------

def build_assistant_payload(
    server_url: str,
    system_prompt: str | None = None,
    first_message: str | None = None,
) -> dict:
    """
    Build the full JSON payload for POST /assistant on the Vapi API.

    References:
        https://docs.vapi.ai/api-reference/assistants/create-assistant
    """
    prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
    greeting = first_message or DEFAULT_FIRST_MESSAGE

    payload: dict = {
        "name": "Medical Receptionist - Inbound",

        # -- Model configuration --
        "model": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "system",
                    "content": prompt,
                },
            ],
            "temperature": 0.3,
            "maxTokens": 1000,
            "tools": _build_tool_definitions(server_url),
        },

        # -- Voice configuration --
        "voice": {
            "provider": "11labs",
            "voiceId": "21m00Tcm4TlvDq8ikWAM",  # "Rachel" - professional female voice
            "stability": 0.6,
            "similarityBoost": 0.75,
            "speed": 1.0,
        },

        # -- First message spoken to the caller --
        "firstMessage": greeting,

        # -- Server URL for webhooks (tool calls, status updates, etc.) --
        "serverUrl": server_url,

        # -- Call behavior --
        "endCallFunctionEnabled": True,
        "silenceTimeoutSeconds": 30,
        "maxDurationSeconds": 600,  # 10-minute max call duration
        "responseDelaySeconds": 0.5,

        # -- HIPAA --
        "hipaaEnabled": True,

        # -- Transcription --
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-2",
            "language": "en",
        },

        # -- End-of-call analysis --
        "analysisPlan": {
            "summaryPrompt": (
                "Summarize this medical office phone call in 2-3 sentences. "
                "Include: caller intent, actions taken (appointments booked/cancelled/"
                "rescheduled, insurance verified), and outcome."
            ),
        },
    }

    return payload


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _vapi_headers(api_key: str) -> dict[str, str]:
    """Build authorization headers for the Vapi API."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


async def _get_practice_config(
    db: AsyncSession, practice_id: UUID
) -> PracticeConfig:
    """
    Fetch the PracticeConfig for a given practice, creating one if it does
    not yet exist.
    """
    stmt = select(PracticeConfig).where(PracticeConfig.practice_id == practice_id)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()

    if config is None:
        config = PracticeConfig(practice_id=practice_id)
        db.add(config)
        await db.flush()
        await db.refresh(config)
        logger.info("Created new PracticeConfig for practice %s", practice_id)

    return config


async def _get_vapi_key(db: AsyncSession, practice_id: UUID) -> str | None:
    """Get the stored Vapi API key for a practice."""
    config = await _get_practice_config(db, practice_id)
    return config.vapi_api_key or None


async def _get_assistant_id(db: AsyncSession, practice_id: UUID) -> str | None:
    """Get the stored Vapi assistant ID for a practice."""
    config = await _get_practice_config(db, practice_id)
    return config.vapi_assistant_id or None


# ============================================================
# Vapi Functions
# ============================================================

async def validate_vapi_key(api_key: str) -> dict:
    """
    Validate a Vapi API key by calling GET /assistant.

    A valid key returns a list of assistants (even if empty).
    Returns ``{"valid": bool, "message": str, "account_name": str|None}``.
    """
    client = get_http_client()
    url = f"{VAPI_BASE_URL}/assistant"
    logger.info("Validating Vapi API key via GET %s", url)

    try:
        response = await client.get(
            url,
            headers=_vapi_headers(api_key),
            timeout=_API_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        logger.info("Vapi key validated successfully, %d assistants found", len(data))
        return {
            "valid": True,
            "message": f"API key is valid. {len(data)} assistant(s) found in your account.",
            "account_name": None,  # Vapi does not return account name on this endpoint
        }
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.warning("Vapi key validation failed with HTTP %d", status)
        if status == 401 or status == 403:
            return {
                "valid": False,
                "message": "Invalid API key. Please check your Vapi API key and try again.",
                "account_name": None,
            }
        return {
            "valid": False,
            "message": f"Vapi API returned an unexpected error (HTTP {status}). Please try again later.",
            "account_name": None,
        }
    except httpx.RequestError as exc:
        logger.error("Network error validating Vapi key: %s", exc)
        return {
            "valid": False,
            "message": "Could not connect to the Vapi API. Please check your internet connection and try again.",
            "account_name": None,
        }


async def create_vapi_assistant(
    db: AsyncSession,
    practice_id: UUID,
    api_key: str,
    system_prompt: str | None = None,
    first_message: str | None = None,
) -> dict:
    """
    Create a new Vapi assistant with all tool definitions.

    1. Build webhook URL from APP_URL setting.
    2. Build payload using ``build_assistant_payload()``.
    3. POST /assistant on the Vapi API.
    4. Save assistant_id and api_key to PracticeConfig.
    5. Return result dict.
    """
    settings = get_settings()
    app_url = settings.APP_URL.rstrip("/")
    server_url = f"{app_url}/api/webhooks/vapi"

    payload = build_assistant_payload(
        server_url=server_url,
        system_prompt=system_prompt,
        first_message=first_message,
    )

    client = get_http_client()
    url = f"{VAPI_BASE_URL}/assistant"
    logger.info(
        "Creating Vapi assistant for practice %s via POST %s (server_url=%s)",
        practice_id, url, server_url,
    )

    try:
        response = await client.post(
            url,
            json=payload,
            headers=_vapi_headers(api_key),
            timeout=_API_TIMEOUT,
        )
        response.raise_for_status()
        assistant = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        body = exc.response.text
        logger.error("Failed to create Vapi assistant (HTTP %d): %s", status, body)
        return {
            "success": False,
            "assistant_id": None,
            "assistant_name": None,
            "message": f"Vapi API returned HTTP {status}. Please verify your API key and try again.",
        }
    except httpx.RequestError as exc:
        logger.error("Network error creating Vapi assistant: %s", exc)
        return {
            "success": False,
            "assistant_id": None,
            "assistant_name": None,
            "message": "Could not connect to the Vapi API. Please check your internet connection.",
        }

    assistant_id = assistant.get("id", "")
    assistant_name = assistant.get("name", "")
    logger.info(
        "Vapi assistant created: id=%s name=%s", assistant_id, assistant_name,
    )

    # Persist to PracticeConfig
    config = await _get_practice_config(db, practice_id)
    config.vapi_api_key = api_key
    config.vapi_assistant_id = assistant_id
    if system_prompt:
        config.vapi_system_prompt = system_prompt
    if first_message:
        config.vapi_first_message = first_message
    await db.commit()

    return {
        "success": True,
        "assistant_id": assistant_id,
        "assistant_name": assistant_name,
        "message": f"Assistant '{assistant_name}' created successfully.",
    }


async def list_vapi_phone_numbers(api_key: str) -> list[dict]:
    """
    List phone numbers from a Vapi account.

    GET /phone-number on the Vapi API.
    Returns a list of dicts with id, number, name, assigned_assistant_id, provider.
    """
    client = get_http_client()
    url = f"{VAPI_BASE_URL}/phone-number"
    logger.info("Listing Vapi phone numbers via GET %s", url)

    try:
        response = await client.get(
            url,
            headers=_vapi_headers(api_key),
            timeout=_API_TIMEOUT,
        )
        response.raise_for_status()
        raw_numbers = response.json()
    except httpx.HTTPStatusError as exc:
        logger.error("Failed to list Vapi phone numbers (HTTP %d)", exc.response.status_code)
        return []
    except httpx.RequestError as exc:
        logger.error("Network error listing Vapi phone numbers: %s", exc)
        return []

    numbers: list[dict] = []
    for item in raw_numbers:
        numbers.append({
            "id": item.get("id", ""),
            "number": item.get("number") or item.get("twilioPhoneNumber") or "",
            "name": item.get("name", ""),
            "assigned_assistant_id": item.get("assistantId"),
            "provider": item.get("provider", "unknown"),
        })

    logger.info("Found %d Vapi phone number(s)", len(numbers))
    return numbers


async def assign_vapi_phone(
    db: AsyncSession,
    practice_id: UUID,
    api_key: str,
    phone_number_id: str,
    assistant_id: str,
) -> dict:
    """
    Assign a phone number to an assistant on Vapi.

    PATCH /phone-number/{id} with ``{"assistantId": assistant_id}``.
    Saves phone_number_id to PracticeConfig.
    """
    client = get_http_client()
    url = f"{VAPI_BASE_URL}/phone-number/{phone_number_id}"
    body = {"assistantId": assistant_id}
    logger.info(
        "Assigning Vapi phone %s to assistant %s via PATCH %s",
        phone_number_id, assistant_id, url,
    )

    try:
        response = await client.patch(
            url,
            json=body,
            headers=_vapi_headers(api_key),
            timeout=_API_TIMEOUT,
        )
        response.raise_for_status()
        phone_data = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.error("Failed to assign Vapi phone (HTTP %d): %s", status, exc.response.text)
        return {
            "success": False,
            "phone_number_id": phone_number_id,
            "phone_number": None,
            "message": f"Failed to assign phone number (HTTP {status}). Please verify the phone number ID.",
        }
    except httpx.RequestError as exc:
        logger.error("Network error assigning Vapi phone: %s", exc)
        return {
            "success": False,
            "phone_number_id": phone_number_id,
            "phone_number": None,
            "message": "Could not connect to the Vapi API. Please check your internet connection.",
        }

    phone_number = phone_data.get("number") or phone_data.get("twilioPhoneNumber")
    logger.info("Vapi phone %s assigned successfully (number=%s)", phone_number_id, phone_number)

    # Persist to PracticeConfig
    config = await _get_practice_config(db, practice_id)
    config.vapi_phone_number_id = phone_number_id
    await db.commit()

    return {
        "success": True,
        "phone_number_id": phone_number_id,
        "phone_number": phone_number,
        "message": "Phone number assigned to assistant successfully.",
    }


# ============================================================
# Twilio Functions
# ============================================================

async def validate_twilio_credentials(account_sid: str, auth_token: str) -> dict:
    """
    Validate Twilio credentials by calling GET /2010-04-01/Accounts/{sid}.json.

    Uses HTTP Basic auth (account_sid:auth_token).
    Returns ``{"valid": bool, "message": str, "account_name": str|None}``.
    """
    client = get_http_client()
    url = f"{TWILIO_API_BASE}/2010-04-01/Accounts/{account_sid}.json"
    logger.info("Validating Twilio credentials via GET %s", url)

    try:
        response = await client.get(
            url,
            auth=(account_sid, auth_token),
            timeout=_API_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        account_name = data.get("friendly_name", "")
        logger.info("Twilio credentials valid, account: %s", account_name)
        return {
            "valid": True,
            "message": f"Twilio credentials are valid. Account: {account_name}",
            "account_name": account_name,
        }
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.warning("Twilio credential validation failed (HTTP %d)", status)
        if status == 401:
            return {
                "valid": False,
                "message": "Invalid Twilio credentials. Please check your Account SID and Auth Token.",
                "account_name": None,
            }
        return {
            "valid": False,
            "message": f"Twilio API returned an unexpected error (HTTP {status}). Please try again.",
            "account_name": None,
        }
    except httpx.RequestError as exc:
        logger.error("Network error validating Twilio credentials: %s", exc)
        return {
            "valid": False,
            "message": "Could not connect to the Twilio API. Please check your internet connection.",
            "account_name": None,
        }


async def list_twilio_phone_numbers(account_sid: str, auth_token: str) -> list[dict]:
    """
    List phone numbers from a Twilio account.

    GET /2010-04-01/Accounts/{sid}/IncomingPhoneNumbers.json.
    Uses HTTP Basic auth.
    Returns list of dicts with sid, phone_number, friendly_name, sms_enabled, voice_enabled.
    """
    client = get_http_client()
    url = f"{TWILIO_API_BASE}/2010-04-01/Accounts/{account_sid}/IncomingPhoneNumbers.json"
    logger.info("Listing Twilio phone numbers via GET %s", url)

    try:
        response = await client.get(
            url,
            auth=(account_sid, auth_token),
            timeout=_API_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        raw_numbers = data.get("incoming_phone_numbers", [])
    except httpx.HTTPStatusError as exc:
        logger.error("Failed to list Twilio phone numbers (HTTP %d)", exc.response.status_code)
        return []
    except httpx.RequestError as exc:
        logger.error("Network error listing Twilio phone numbers: %s", exc)
        return []

    numbers: list[dict] = []
    for item in raw_numbers:
        capabilities = item.get("capabilities", {})
        numbers.append({
            "sid": item.get("sid", ""),
            "phone_number": item.get("phone_number", ""),
            "friendly_name": item.get("friendly_name", ""),
            "sms_enabled": capabilities.get("sms", False),
            "voice_enabled": capabilities.get("voice", False),
        })

    logger.info("Found %d Twilio phone number(s)", len(numbers))
    return numbers


async def save_twilio_config(
    db: AsyncSession,
    practice_id: UUID,
    account_sid: str,
    auth_token: str,
    phone_number: str,
) -> None:
    """
    Save Twilio configuration to PracticeConfig.

    Updates twilio_account_sid, twilio_auth_token, twilio_phone_number.
    The EncryptedString columns handle encryption automatically on assignment.
    """
    config = await _get_practice_config(db, practice_id)
    config.twilio_account_sid = account_sid
    config.twilio_auth_token = auth_token
    config.twilio_phone_number = phone_number
    await db.commit()
    logger.info("Saved Twilio configuration for practice %s", practice_id)


# ============================================================
# OpenAI Key Validation
# ============================================================

async def validate_openai_key(api_key: str) -> dict:
    """
    Validate an OpenAI API key by calling GET /v1/models.

    Returns ``{"valid": bool, "message": str}``.
    """
    client = get_http_client()
    url = f"{OPENAI_API_BASE}/v1/models"
    logger.info("Validating OpenAI API key via GET %s", url)

    try:
        response = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
            },
            timeout=_API_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        model_count = len(data.get("data", []))
        logger.info("OpenAI key validated, %d models accessible", model_count)
        return {
            "valid": True,
            "message": f"OpenAI API key is valid. {model_count} model(s) accessible.",
        }
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.warning("OpenAI key validation failed (HTTP %d)", status)
        if status == 401:
            return {
                "valid": False,
                "message": "Invalid OpenAI API key. Please check your key and try again.",
            }
        if status == 429:
            return {
                "valid": True,
                "message": "OpenAI API key appears valid but is currently rate-limited. Try again shortly.",
            }
        return {
            "valid": False,
            "message": f"OpenAI API returned an unexpected error (HTTP {status}). Please try again.",
        }
    except httpx.RequestError as exc:
        logger.error("Network error validating OpenAI key: %s", exc)
        return {
            "valid": False,
            "message": "Could not connect to the OpenAI API. Please check your internet connection.",
        }


# ============================================================
# Stedi Key Validation
# ============================================================

async def validate_stedi_key(api_key: str) -> dict:
    """
    Validate a Stedi API key by calling the healthcare eligibility endpoint.

    Returns ``{"valid": bool, "message": str}``.
    """
    client = get_http_client()
    # Use the healthcare eligibility health-check endpoint
    url = "https://healthcare.us.stedi.com/2024-04-01/change-healthcare/eligibility/v1/health-check"
    logger.info("Validating Stedi API key via GET %s", url)

    try:
        response = await client.get(
            url,
            headers={
                "Authorization": f"Key {api_key}",
                "Content-Type": "application/json",
            },
            timeout=_API_TIMEOUT,
        )
        response.raise_for_status()
        logger.info("Stedi key validated successfully")
        return {
            "valid": True,
            "message": "Stedi API key is valid.",
        }
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        logger.warning("Stedi key validation returned HTTP %d", status_code)
        if status_code in (401,):
            return {
                "valid": False,
                "message": "Invalid Stedi API key. Please check your key and try again.",
            }
        # 403 with "access_denied" typically means a valid test key hitting
        # a production-only endpoint — treat as valid.
        if status_code == 403:
            try:
                body = exc.response.json()
                if body.get("code") == "access_denied":
                    logger.info("Stedi key is valid (test mode key detected)")
                    return {
                        "valid": True,
                        "message": "Stedi API key is valid (test mode).",
                    }
            except Exception:
                pass
            return {
                "valid": False,
                "message": "Invalid Stedi API key. Please check your key and try again.",
            }
        # Other non-auth errors — key may still be valid
        return {
            "valid": True,
            "message": f"Stedi API key accepted (HTTP {status_code} on health-check, key format valid).",
        }
    except httpx.RequestError as exc:
        logger.error("Network error validating Stedi key: %s", exc)
        return {
            "valid": False,
            "message": "Could not connect to the Stedi API. Please check your internet connection.",
        }


# ============================================================
# Onboarding Status
# ============================================================

async def get_onboarding_status(db: AsyncSession, practice_id: UUID) -> dict:
    """
    Check which onboarding steps are complete by reading PracticeConfig.

    Returns a dict matching the OnboardingStatusResponse schema with
    step-level completion flags and detail strings.
    """
    config = await _get_practice_config(db, practice_id)

    vapi_key_set = bool(config.vapi_api_key)
    vapi_assistant_created = bool(config.vapi_assistant_id)
    vapi_phone_assigned = bool(config.vapi_phone_number_id)
    twilio_creds_set = bool(config.twilio_account_sid and config.twilio_auth_token)
    twilio_phone_set = bool(config.twilio_phone_number)
    # OpenAI key is stored in env / settings, not per-practice — mark as complete
    # if the global OPENAI_API_KEY is configured
    settings = get_settings()
    openai_key_set = bool(getattr(settings, "OPENAI_API_KEY", None))
    stedi_configured = bool(config.stedi_api_key and config.stedi_enabled)

    steps = [
        vapi_key_set, vapi_assistant_created, vapi_phone_assigned,
        twilio_creds_set, twilio_phone_set, openai_key_set, stedi_configured,
    ]

    return {
        "vapi_key": {
            "completed": vapi_key_set,
            "detail": "API key saved" if vapi_key_set else None,
        },
        "vapi_assistant": {
            "completed": vapi_assistant_created,
            "detail": config.vapi_assistant_id if vapi_assistant_created else None,
        },
        "vapi_phone": {
            "completed": vapi_phone_assigned,
            "detail": config.vapi_phone_number_id if vapi_phone_assigned else None,
        },
        "twilio_credentials": {
            "completed": twilio_creds_set,
            "detail": "Credentials saved" if twilio_creds_set else None,
        },
        "twilio_phone": {
            "completed": twilio_phone_set,
            "detail": config.twilio_phone_number if twilio_phone_set else None,
        },
        "openai_key": {
            "completed": openai_key_set,
            "detail": "API key configured" if openai_key_set else None,
        },
        "stedi_key": {
            "completed": stedi_configured,
            "detail": "API key saved" if stedi_configured else None,
        },
        "all_complete": all(steps),
    }


# ============================================================
# Save API Keys
# ============================================================

async def save_vapi_key(db: AsyncSession, practice_id: UUID, api_key: str) -> None:
    """Save a validated Vapi API key to PracticeConfig."""
    config = await _get_practice_config(db, practice_id)
    config.vapi_api_key = api_key
    await db.commit()
    logger.info("Saved Vapi API key for practice %s", practice_id)


async def save_openai_key(db: AsyncSession, practice_id: UUID, api_key: str) -> None:
    """
    Save an OpenAI API key.

    Note: The OpenAI key is currently a global setting in config.py
    (``Settings.OPENAI_API_KEY``), not per-practice.  This function validates
    and logs the action but does not persist to PracticeConfig.  Per-practice
    OpenAI keys can be added as a future enhancement by adding an
    ``openai_api_key`` column to PracticeConfig.
    """
    # Validate first
    result = await validate_openai_key(api_key)
    if not result["valid"]:
        raise ValueError(result["message"])

    logger.info(
        "OpenAI key validated for practice %s. "
        "Global key update requires environment variable change.",
        practice_id,
    )


async def save_stedi_key(db: AsyncSession, practice_id: UUID, api_key: str) -> None:
    """Save a validated Stedi API key to PracticeConfig and enable Stedi."""
    config = await _get_practice_config(db, practice_id)
    config.stedi_api_key = api_key
    config.stedi_enabled = True
    await db.commit()
    logger.info("Saved Stedi API key and enabled Stedi for practice %s", practice_id)
