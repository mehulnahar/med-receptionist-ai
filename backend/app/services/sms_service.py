"""
SMS service for the AI Medical Receptionist.

Handles sending SMS appointment confirmations via Twilio with bilingual
(English/Spanish) template support. All operations are practice-scoped
with per-practice credential overrides falling back to global settings.
"""

import logging
import re
from datetime import date, time
from uuid import UUID
from zoneinfo import ZoneInfo

# Strict E.164 format: + followed by 1-15 digits, starting with non-zero
_E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")

# Cache Twilio Client instances keyed by (account_sid, auth_token).
# Avoids re-creating the HTTP client on every SMS send (~500-600/day).
# Bounded to 16 entries to prevent unbounded growth on credential rotation.
from functools import lru_cache

@lru_cache(maxsize=16)
def _get_twilio_client(account_sid: str, auth_token: str):
    from twilio.rest import Client
    return Client(account_sid, auth_token)

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.appointment import Appointment
from app.models.patient import Patient
from app.models.practice import Practice
from app.models.practice_config import PracticeConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default SMS templates (used when practice has no custom template)
# ---------------------------------------------------------------------------

DEFAULT_TEMPLATES = {
    "en": (
        "Your appointment with {doctor} is confirmed for {date} at {time}. "
        "Address: {address}. Please bring your insurance card and photo ID. "
        "To cancel or reschedule, call {phone}."
    ),
    "es": (
        "Su cita con {doctor} esta confirmada para el {date} a las {time}. "
        "Direccion: {address}. Por favor traiga su tarjeta de seguro e "
        "identificacion con foto. Para cancelar o reprogramar, llame al {phone}."
    ),
}

# Spanish day and month names for locale-aware formatting
_SPANISH_DAYS = {
    0: "Lunes",
    1: "Martes",
    2: "Miercoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sabado",
    6: "Domingo",
}

_SPANISH_MONTHS = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}


# ---------------------------------------------------------------------------
# 1. send_appointment_confirmation
# ---------------------------------------------------------------------------

async def send_appointment_confirmation(
    db: AsyncSession,
    practice_id: UUID,
    appointment_id: UUID,
) -> dict:
    """
    Send an SMS confirmation for a booked appointment.

    Fetches the appointment with its patient and practice relations, renders
    the appropriate bilingual template, sends via Twilio, and marks the
    appointment as SMS-confirmed.

    Returns a result dict:
        {"success": bool, "message_sid": str|None, "error": str|None,
         "to": str, "body": str}
    """
    try:
        # Fetch appointment with patient and practice
        stmt = (
            select(Appointment)
            .where(
                and_(
                    Appointment.id == appointment_id,
                    Appointment.practice_id == practice_id,
                )
            )
        )
        result = await db.execute(stmt)
        appointment = result.scalar_one_or_none()

        if not appointment:
            logger.error(
                "Appointment %s not found for practice %s",
                appointment_id, practice_id,
            )
            return {
                "success": False,
                "message_sid": None,
                "error": "Appointment not found",
                "to": "",
                "body": "",
            }

        # Load related objects (lazy="selectin" should have them loaded,
        # but access them to be safe)
        patient: Patient = appointment.patient
        practice: Practice = appointment.practice

        if not patient:
            logger.error("Patient not found for appointment %s", appointment_id)
            return {
                "success": False,
                "message_sid": None,
                "error": "Patient not found for appointment",
                "to": "",
                "body": "",
            }

        # Check if SMS confirmation is enabled for this practice
        config_stmt = select(PracticeConfig).where(
            PracticeConfig.practice_id == practice_id
        )
        config_result = await db.execute(config_stmt)
        config: PracticeConfig | None = config_result.scalar_one_or_none()

        if not config or not config.sms_confirmation_enabled:
            logger.info(
                "SMS confirmation disabled for practice %s, skipping",
                practice_id,
            )
            return {
                "success": False,
                "message_sid": None,
                "error": "SMS confirmation is disabled for this practice",
                "to": patient.phone or "",
                "body": "",
            }

        # Check patient has a phone number
        if not patient.phone:
            logger.warning(
                "Patient %s has no phone number, cannot send SMS",
                patient.id,
            )
            return {
                "success": False,
                "message_sid": None,
                "error": "Patient has no phone number",
                "to": "",
                "body": "",
            }

        # Determine language
        language = patient.language_preference or "en"

        # Resolve timezone
        timezone_str = practice.timezone or "America/New_York"

        # Format date and time for display
        formatted_date, formatted_time = format_appointment_datetime(
            appointment.date,
            appointment.time,
            timezone_str,
            language,
        )

        # Build template variables
        variables = {
            "doctor": practice.name,
            "date": formatted_date,
            "time": formatted_time,
            "address": practice.address or "",
            "patient_name": f"{patient.first_name} {patient.last_name}",
            "phone": practice.phone or "",
        }

        # Select template source (practice custom or default)
        template_dict = (
            config.sms_confirmation_template
            if config.sms_confirmation_template
            else DEFAULT_TEMPLATES
        )

        # Render the message body
        body = render_sms_template(template_dict, language, variables)

        # Get Twilio credentials
        try:
            account_sid, auth_token, from_phone = await get_twilio_credentials(
                db, practice_id
            )
        except ValueError as cred_err:
            logger.error(
                "Twilio credentials missing for practice %s: %s",
                practice_id, cred_err,
            )
            return {
                "success": False,
                "message_sid": None,
                "error": f"Twilio credentials not configured: {cred_err}",
                "to": patient.phone,
                "body": body,
            }

        # Send the SMS
        send_result = await send_sms(
            to_number=patient.phone,
            from_number=from_phone,
            body=body,
            account_sid=account_sid,
            auth_token=auth_token,
        )

        # Update appointment on success — commit immediately since the SMS
        # was already sent (Twilio confirmed). Rolling this back would leave
        # sms_confirmation_sent=False even though the patient received the SMS.
        if send_result["success"]:
            appointment.sms_confirmation_sent = True
            await db.flush()
            # NOTE: Do NOT commit here — let the caller control the transaction
            # boundary so booking + reminders + SMS confirmation are atomic.
            logger.info(
                "SMS confirmation sent for appointment %s to %s (SID: %s)",
                appointment_id, patient.phone, send_result.get("message_sid"),
            )
        else:
            logger.error(
                "Failed to send SMS for appointment %s: %s",
                appointment_id, send_result.get("error"),
            )

        return {
            "success": send_result["success"],
            "message_sid": send_result.get("message_sid"),
            "error": send_result.get("error"),
            "to": patient.phone,
            "body": body,
        }

    except Exception as e:
        logger.exception("Unexpected error sending SMS confirmation: %s", e)
        return {
            "success": False,
            "message_sid": None,
            "error": str(e),
            "to": "",
            "body": "",
        }


# ---------------------------------------------------------------------------
# 2. render_sms_template
# ---------------------------------------------------------------------------

def render_sms_template(
    template_dict: dict,
    language: str,
    variables: dict,
) -> str:
    """
    Render an SMS template string with variable substitution.

    Selects the template for the given language code, falling back to "en"
    if not found. Replaces {variable} placeholders with actual values.
    If no template is found at all, uses a sensible default English template.
    """
    # Try the requested language, then fall back to English
    template = template_dict.get(language) or template_dict.get("en")

    # If the dict was empty or had no matching keys, use the built-in default
    if not template:
        template = DEFAULT_TEMPLATES.get(language) or DEFAULT_TEMPLATES["en"]

    # Replace placeholders - use str.format_map with a defaultdict-like approach
    # so missing keys don't raise KeyError
    try:
        rendered = template.format_map(_SafeFormatDict(variables))
    except Exception:
        # If anything goes wrong with formatting, do simple string replacement
        rendered = template
        for key, value in variables.items():
            rendered = rendered.replace(f"{{{key}}}", str(value))

    return rendered


class _SafeFormatDict(dict):
    """Dict subclass that returns the placeholder itself for missing keys."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


# ---------------------------------------------------------------------------
# 3. send_sms
# ---------------------------------------------------------------------------

async def send_sms(
    to_number: str,
    from_number: str,
    body: str,
    account_sid: str,
    auth_token: str,
    max_retries: int = 3,
) -> dict:
    """
    Low-level Twilio SMS send function with retry logic.

    Creates a Twilio Client and sends the message. On transient failures
    (network errors, 5xx from Twilio) retries up to ``max_retries`` times
    with exponential back-off (1s, 2s, 4s).

    Returns a result dict:
        {"success": True, "message_sid": "SM..."} on success
        {"success": False, "error": "..."} on failure

    Handles both TwilioRestException and general network/runtime errors.
    """
    # Validate phone numbers before hitting Twilio API
    if not _E164_PATTERN.match(to_number):
        logger.error("send_sms: invalid to_number format: %s", to_number[:20])
        return {"success": False, "error": f"Invalid phone number format: {to_number}"}
    if not _E164_PATTERN.match(from_number):
        logger.error("send_sms: invalid from_number format: %s", from_number[:20])
        return {"success": False, "error": f"Invalid from_number format: {from_number}"}

    try:
        from twilio.rest import Client
        from twilio.base.exceptions import TwilioRestException
    except ImportError:
        logger.error(
            "twilio package is not installed. "
            "Install it with: pip install twilio"
        )
        return {
            "success": False,
            "error": "Twilio SDK not installed",
        }

    import asyncio

    client = _get_twilio_client(account_sid, auth_token)
    last_error: str = ""

    for attempt in range(1, max_retries + 1):
        try:
            # Twilio's SDK is synchronous — run in a thread to avoid blocking
            # the async event loop (critical for concurrent webhook handling).
            message = await asyncio.to_thread(
                client.messages.create,
                to=to_number,
                from_=from_number,
                body=body,
            )
            logger.info("SMS sent successfully: SID=%s, to=%s (attempt %d)", message.sid, to_number, attempt)
            return {
                "success": True,
                "message_sid": message.sid,
            }
        except TwilioRestException as e:
            last_error = f"Twilio error: {e.msg}" if hasattr(e, "msg") else str(e)
            twilio_status = getattr(e, "status", None)
            # 429 = rate limited — retry with backoff (not a permanent failure)
            if twilio_status == 429:
                logger.warning("Twilio rate limit (429) sending SMS to %s (attempt %d/%d)", to_number, attempt, max_retries)
            elif twilio_status and 400 <= twilio_status < 500:
                # Other 4xx client errors are permanent — don't retry
                logger.error("Twilio client error sending SMS to %s (attempt %d/%d): %s", to_number, attempt, max_retries, e)
                return {"success": False, "error": last_error}
            else:
                logger.warning("Twilio server error sending SMS to %s (attempt %d/%d): %s", to_number, attempt, max_retries, e)
        except Exception as e:
            last_error = f"Network/runtime error: {str(e)}"
            logger.warning("Transient error sending SMS to %s (attempt %d/%d): %s", to_number, attempt, max_retries, e)

        # Exponential back-off before retry (1s, 2s, 4s, ...)
        if attempt < max_retries:
            await asyncio.sleep(2 ** (attempt - 1))

    logger.error("SMS to %s failed after %d attempts: %s", to_number, max_retries, last_error)
    return {
        "success": False,
        "error": last_error,
    }


# ---------------------------------------------------------------------------
# 4. send_custom_sms
# ---------------------------------------------------------------------------

async def send_custom_sms(
    db: AsyncSession,
    practice_id: UUID,
    to_number: str,
    body: str,
) -> dict:
    """
    Send an arbitrary SMS message (e.g., manual send from the dashboard).

    Resolves Twilio credentials for the practice and delegates to send_sms().
    Returns the same result dict format as send_sms().
    """
    try:
        account_sid, auth_token, from_phone = await get_twilio_credentials(
            db, practice_id
        )
    except ValueError as e:
        logger.error("Cannot send custom SMS for practice %s: %s", practice_id, e)
        return {
            "success": False,
            "error": str(e),
        }

    result = await send_sms(
        to_number=to_number,
        from_number=from_phone,
        body=body,
        account_sid=account_sid,
        auth_token=auth_token,
    )

    if result["success"]:
        logger.info(
            "Custom SMS sent for practice %s to %s (SID: %s)",
            practice_id, to_number, result.get("message_sid"),
        )
    else:
        logger.error(
            "Failed to send custom SMS for practice %s to %s: %s",
            practice_id, to_number, result.get("error"),
        )

    return result


# ---------------------------------------------------------------------------
# 5. get_twilio_credentials
# ---------------------------------------------------------------------------

async def get_twilio_credentials(
    db: AsyncSession,
    practice_id: UUID,
) -> tuple[str, str, str]:
    """
    Resolve Twilio credentials for a practice.

    Checks PracticeConfig for per-practice SID, auth token, and phone number.
    Falls back to global settings for SID and auth token if the practice-level
    values are not set.

    Returns (account_sid, auth_token, from_phone).
    Raises ValueError if credentials cannot be resolved.
    """
    # Load practice config
    config_stmt = select(PracticeConfig).where(
        PracticeConfig.practice_id == practice_id
    )
    config_result = await db.execute(config_stmt)
    config: PracticeConfig | None = config_result.scalar_one_or_none()

    settings = get_settings()

    # Resolve account SID: practice override -> global
    account_sid = (
        (config.twilio_account_sid if config and config.twilio_account_sid else None)
        or settings.TWILIO_ACCOUNT_SID
    )

    # Resolve auth token: practice override -> global
    auth_token = (
        (config.twilio_auth_token if config and config.twilio_auth_token else None)
        or settings.TWILIO_AUTH_TOKEN
    )

    # From phone must come from practice config (no global fallback makes sense)
    from_phone = config.twilio_phone_number if config else None

    if not account_sid:
        raise ValueError(
            f"Twilio Account SID not configured for practice {practice_id} "
            "and no global SID is set"
        )

    if not auth_token:
        raise ValueError(
            f"Twilio Auth Token not configured for practice {practice_id} "
            "and no global token is set"
        )

    if not from_phone:
        raise ValueError(
            f"Twilio phone number not configured for practice {practice_id}"
        )

    return (account_sid, auth_token, from_phone)


# ---------------------------------------------------------------------------
# 6. format_appointment_datetime
# ---------------------------------------------------------------------------

def format_appointment_datetime(
    appt_date: date,
    appt_time: time,
    timezone_str: str,
    language: str,
) -> tuple[str, str]:
    """
    Format appointment date and time for SMS display in the practice timezone.

    English format:  "Monday, February 24, 2025" / "9:00 AM"
    Spanish format:  "Lunes, 24 de febrero de 2025" / "9:00 AM"

    Returns (formatted_date, formatted_time).
    """
    try:
        tz = ZoneInfo(timezone_str)
    except (KeyError, Exception):
        # Fall back to Eastern if the timezone string is invalid
        logger.warning("Invalid timezone '%s', falling back to America/New_York", timezone_str)
        tz = ZoneInfo("America/New_York")

    # Build a timezone-aware datetime for proper formatting
    # (date and time columns store naive values in practice timezone context)
    from datetime import datetime as dt
    aware_dt = dt.combine(appt_date, appt_time, tzinfo=tz)

    # Format time: "9:00 AM" style (no leading zero on hour)
    # On Windows, %-I is not supported; use %#I instead as fallback
    try:
        formatted_time = aware_dt.strftime("%-I:%M %p")
    except ValueError:
        formatted_time = aware_dt.strftime("%#I:%M %p")

    # Format date based on language
    if language == "es":
        day_name = _SPANISH_DAYS.get(appt_date.weekday(), "")
        month_name = _SPANISH_MONTHS.get(appt_date.month, "")
        formatted_date = f"{day_name}, {appt_date.day} de {month_name} de {appt_date.year}"
    else:
        # English: "Monday, February 24, 2025"
        formatted_date = aware_dt.strftime("%A, %B %d, %Y")
        # Remove leading zero from day if present (e.g., "February 05" -> "February 5")
        # strftime %d always pads; clean it up
        parts = formatted_date.split(", ")
        if len(parts) == 3:
            # parts = ["Monday", "February 05", "2025"]
            month_day = parts[1]
            tokens = month_day.split(" ")
            if len(tokens) == 2 and tokens[1].startswith("0"):
                tokens[1] = tokens[1].lstrip("0")
                parts[1] = " ".join(tokens)
            formatted_date = ", ".join(parts)

    return (formatted_date, formatted_time)
