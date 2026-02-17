#!/usr/bin/env python3
"""
Create a new inbound Vapi assistant for the AI Medical Receptionist.

This script uses the Vapi REST API to create a fully-configured assistant
with all 8 tool functions, model/voice settings, and server URL for webhooks.

Usage:
    python scripts/setup_vapi_assistant.py
    python scripts/setup_vapi_assistant.py --assign-phone PHONE_NUMBER_ID

Environment:
    VAPI_API_KEY  - Vapi API key (read from env or ../.env)
    APP_URL       - Backend URL for the webhook server (default: http://localhost:8000)

The script does NOT modify any existing assistants or dashboard settings.
It always creates a NEW assistant.
"""

import argparse
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VAPI_BASE_URL = "https://api.vapi.ai"

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
    webhook endpoint. Vapi will POST tool-call events to this URL.
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
# API helpers
# ---------------------------------------------------------------------------

def _headers(api_key: str) -> dict[str, str]:
    """Build the authorization headers for the Vapi API."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def create_assistant(api_key: str, payload: dict) -> dict:
    """
    Create a new Vapi assistant via POST /assistant.

    Returns the full assistant object from the API response.
    Raises on HTTP or network errors.
    """
    url = f"{VAPI_BASE_URL}/assistant"
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, json=payload, headers=_headers(api_key))
        response.raise_for_status()
        return response.json()


def assign_phone_number(api_key: str, phone_number_id: str, assistant_id: str) -> dict:
    """
    Assign an assistant to a Vapi phone number via PATCH /phone-number/{id}.

    This updates the phone number to route inbound calls to the given assistant.
    Returns the updated phone number object.
    """
    url = f"{VAPI_BASE_URL}/phone-number/{phone_number_id}"
    body = {
        "assistantId": assistant_id,
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.patch(url, json=body, headers=_headers(api_key))
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# Environment loading
# ---------------------------------------------------------------------------

def load_config() -> tuple[str, str]:
    """
    Load the VAPI_API_KEY and APP_URL from environment or .env file.

    Returns (api_key, app_url).
    Exits with an error message if VAPI_API_KEY is not set.
    """
    # Try loading from the project root .env file
    project_root = Path(__file__).resolve().parent.parent.parent  # backend/scripts -> backend -> root
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    # Also try the backend-level .env
    backend_env = Path(__file__).resolve().parent.parent / ".env"
    if backend_env.exists():
        load_dotenv(backend_env, override=False)

    api_key = os.environ.get("VAPI_API_KEY", "").strip()
    app_url = os.environ.get("APP_URL", "http://localhost:8000").strip()

    if not api_key:
        print("ERROR: VAPI_API_KEY is not set.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Set it in one of these ways:", file=sys.stderr)
        print(f"  1. Add VAPI_API_KEY=your-key to {env_path}", file=sys.stderr)
        print("  2. Export it: export VAPI_API_KEY=your-key", file=sys.stderr)
        print("  3. Get your key from: https://dashboard.vapi.ai/account", file=sys.stderr)
        sys.exit(1)

    return api_key, app_url


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Create a new Vapi assistant for the AI Medical Receptionist.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python scripts/setup_vapi_assistant.py
  python scripts/setup_vapi_assistant.py --assign-phone phn_abc123def456

Environment variables:
  VAPI_API_KEY    Your Vapi API key (required)
  APP_URL         Backend webhook URL (default: http://localhost:8000)
""",
    )
    parser.add_argument(
        "--assign-phone",
        metavar="PHONE_NUMBER_ID",
        help="Assign the new assistant to this Vapi phone number ID after creation",
    )
    parser.add_argument(
        "--system-prompt",
        metavar="FILE",
        help="Read the system prompt from a file instead of using the default",
    )
    parser.add_argument(
        "--first-message",
        metavar="TEXT",
        help="Override the default first message spoken to callers",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the payload that would be sent without making any API calls",
    )
    args = parser.parse_args()

    # Load configuration
    api_key, app_url = load_config()
    server_url = f"{app_url}/api/webhooks/vapi"

    # Load optional system prompt from file
    system_prompt = None
    if args.system_prompt:
        prompt_path = Path(args.system_prompt)
        if not prompt_path.exists():
            print(f"ERROR: System prompt file not found: {prompt_path}", file=sys.stderr)
            sys.exit(1)
        system_prompt = prompt_path.read_text(encoding="utf-8").strip()
        print(f"Loaded system prompt from: {prompt_path}")

    # Build the assistant payload
    payload = build_assistant_payload(
        server_url=server_url,
        system_prompt=system_prompt,
        first_message=args.first_message,
    )

    print("=" * 70)
    print("  Vapi Assistant Setup - AI Medical Receptionist")
    print("=" * 70)
    print()
    print(f"  Server URL:   {server_url}")
    print(f"  Model:        openai / gpt-4o-mini")
    print(f"  Voice:        11labs / Rachel (21m00Tcm4TlvDq8ikWAM)")
    print(f"  HIPAA:        Enabled")
    print(f"  Max duration: 600s (10 min)")
    print(f"  Silence timeout: 30s")
    print(f"  Tools:        {len(payload['model']['tools'])} functions defined")
    print()

    # Dry-run mode: print payload and exit
    if args.dry_run:
        import json
        print("DRY RUN - Payload that would be sent:")
        print("-" * 70)
        print(json.dumps(payload, indent=2))
        print("-" * 70)
        sys.exit(0)

    # -----------------------------------------------------------------------
    # Create the assistant
    # -----------------------------------------------------------------------
    print("Creating Vapi assistant...")
    try:
        assistant = create_assistant(api_key, payload)
    except httpx.HTTPStatusError as e:
        print(f"ERROR: Vapi API returned HTTP {e.response.status_code}", file=sys.stderr)
        print(f"Response: {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"ERROR: Failed to connect to Vapi API: {e}", file=sys.stderr)
        sys.exit(1)

    assistant_id = assistant.get("id", "UNKNOWN")
    print()
    print(f"  Assistant created successfully!")
    print(f"  Assistant ID: {assistant_id}")
    print(f"  Name:         {assistant.get('name', 'N/A')}")
    print()

    # -----------------------------------------------------------------------
    # Optionally assign to a phone number
    # -----------------------------------------------------------------------
    if args.assign_phone:
        print(f"Assigning assistant to phone number: {args.assign_phone}...")
        try:
            phone_result = assign_phone_number(api_key, args.assign_phone, assistant_id)
            print(f"  Phone number updated successfully!")
            print(f"  Phone Number ID: {phone_result.get('id', args.assign_phone)}")
            phone_num = phone_result.get("number") or phone_result.get("twilioPhoneNumber", "N/A")
            print(f"  Number:          {phone_num}")
            print()
        except httpx.HTTPStatusError as e:
            print(f"WARNING: Failed to assign phone number (HTTP {e.response.status_code})", file=sys.stderr)
            print(f"Response: {e.response.text}", file=sys.stderr)
            print("The assistant was created but not assigned to a phone number.", file=sys.stderr)
            print(f"You can manually assign it in the Vapi dashboard.", file=sys.stderr)
            print()
        except httpx.RequestError as e:
            print(f"WARNING: Failed to connect to Vapi API for phone assignment: {e}", file=sys.stderr)
            print()

    # -----------------------------------------------------------------------
    # Print next steps
    # -----------------------------------------------------------------------
    print("=" * 70)
    print("  NEXT STEPS")
    print("=" * 70)
    print()
    print("  1. Save the assistant ID in your practice configuration:")
    print(f"     UPDATE practice_configs")
    print(f"       SET vapi_assistant_id = '{assistant_id}'")
    print(f"       WHERE practice_id = '<your-practice-uuid>';")
    print()

    if not args.assign_phone:
        print("  2. Assign the assistant to your Vapi phone number:")
        print(f"     python scripts/setup_vapi_assistant.py --assign-phone <PHONE_NUMBER_ID>")
        print()
        print("     Or manually in the Vapi dashboard:")
        print("     https://dashboard.vapi.ai/phone-numbers")
        print()
        print("  3. Ensure your webhook server is accessible from the internet:")
        print(f"     Current server URL: {server_url}")
        print("     For local development, use ngrok or similar tunneling tool:")
        print("     ngrok http 8000")
        print("     Then update APP_URL in your .env file with the ngrok URL.")
    else:
        print("  2. Ensure your webhook server is accessible from the internet:")
        print(f"     Current server URL: {server_url}")
        print("     For local development, use ngrok or similar tunneling tool:")
        print("     ngrok http 8000")
        print("     Then update APP_URL in your .env file with the ngrok URL.")

    print()
    print("  Test the assistant:")
    print("     - Call the assigned phone number, or")
    print("     - Use the Vapi dashboard test call feature:")
    print(f"       https://dashboard.vapi.ai/assistants/{assistant_id}")
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
