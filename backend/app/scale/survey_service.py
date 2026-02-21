"""
Post-visit satisfaction survey + Google review collection service.

Sends patients an SMS after their appointment, collects ratings,
and prompts happy patients to leave a Google review.
"""

import hashlib
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

logger = logging.getLogger(__name__)

SURVEY_TOKEN_EXPIRY_HOURS = 72


# ---------------------------------------------------------------------------
# Survey config (per-practice, stored in practices.config JSONB)
# ---------------------------------------------------------------------------

DEFAULT_SURVEY_CONFIG = {
    "enabled": True,
    "delay_hours": 2,
    "include_google_review": True,
    "google_review_url": "",
    "min_rating_for_review": 4,
    "message_template_en": (
        "How was your visit with Dr. {provider_name}? "
        "Rate 1-5 by replying, or tap: {link}"
    ),
    "message_template_es": (
        "Como fue su visita con Dr. {provider_name}? "
        "Responda 1-5 o toque: {link}"
    ),
}


def _get_survey_config(practice_config: dict) -> dict:
    """Merge practice config with defaults."""
    survey = practice_config.get("survey", {})
    merged = dict(DEFAULT_SURVEY_CONFIG)
    merged.update(survey)
    return merged


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def _create_survey_token(appointment_id: str, practice_id: str) -> str:
    settings = get_settings()
    payload = {
        "type": "survey",
        "appointment_id": appointment_id,
        "practice_id": practice_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=SURVEY_TOKEN_EXPIRY_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def _decode_survey_token(token: str) -> Optional[dict]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        logger.warning("Survey token expired")
        return None
    except jwt.InvalidTokenError:
        logger.warning("Invalid survey token")
        return None


# ---------------------------------------------------------------------------
# Core service functions
# ---------------------------------------------------------------------------

async def send_post_visit_survey(
    db: AsyncSession, appointment_id: str
) -> Optional[dict]:
    """Send a post-visit survey SMS for a completed appointment."""
    # Fetch appointment + patient + provider details
    result = await db.execute(
        text("""
            SELECT a.id, a.practice_id, a.patient_id,
                   p.first_name AS patient_first, p.last_name AS patient_last,
                   p.phone AS patient_phone, p.preferred_language,
                   u.first_name AS provider_first, u.last_name AS provider_last
            FROM appointments a
            JOIN patients p ON a.patient_id = p.id
            LEFT JOIN users u ON a.provider_id = u.id
            WHERE a.id = :appt_id
        """),
        {"appt_id": appointment_id},
    )
    row = result.fetchone()
    if not row or not row.patient_phone:
        return None

    # Check if survey already sent
    existing = await db.execute(
        text("SELECT id FROM surveys WHERE appointment_id = :aid"),
        {"aid": appointment_id},
    )
    if existing.fetchone():
        logger.info("Survey already sent for appointment %s", appointment_id)
        return None

    # Get practice survey config
    config_result = await db.execute(
        text("SELECT config FROM practices WHERE id = :pid"),
        {"pid": str(row.practice_id)},
    )
    config_row = config_result.fetchone()
    practice_config = config_row.config if config_row and config_row.config else {}
    survey_config = _get_survey_config(practice_config)

    if not survey_config["enabled"]:
        return None

    # Create survey token and link
    settings = get_settings()
    token = _create_survey_token(str(row.id), str(row.practice_id))
    link = f"{settings.APP_URL}/survey/{token}"

    provider_name = f"{row.provider_first or ''} {row.provider_last or ''}".strip()
    lang = (row.preferred_language or "en").lower()

    # Choose template
    if lang.startswith("es"):
        template = survey_config["message_template_es"]
    else:
        template = survey_config["message_template_en"]

    message = template.format(provider_name=provider_name, link=link)

    # Send SMS
    sms_sent = await _send_survey_sms(row.patient_phone, message, str(row.practice_id))

    # Record survey
    await db.execute(
        text("""
            INSERT INTO surveys (id, practice_id, appointment_id, patient_id,
                                 patient_phone, token_hash, message_sent, status, created_at)
            VALUES (gen_random_uuid(), :pid, :aid, :patient_id, :phone,
                    :token_hash, :message, :status, NOW())
        """),
        {
            "pid": str(row.practice_id),
            "aid": appointment_id,
            "patient_id": str(row.patient_id),
            "phone": row.patient_phone,
            "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "message": message,
            "status": "sent" if sms_sent else "failed",
        },
    )
    await db.commit()

    return {
        "appointment_id": appointment_id,
        "patient_phone": row.patient_phone,
        "status": "sent" if sms_sent else "failed",
    }


async def process_survey_response(
    db: AsyncSession, token: str, rating: int, feedback: str = ""
) -> dict:
    """Process a patient's survey response."""
    payload = _decode_survey_token(token)
    if not payload:
        return {"error": "Invalid or expired survey link"}

    appointment_id = payload["appointment_id"]
    practice_id = payload["practice_id"]

    # Clamp rating
    rating = max(1, min(5, rating))

    # Update survey record
    await db.execute(
        text("""
            UPDATE surveys SET
                rating = :rating,
                feedback = :feedback,
                status = 'responded',
                responded_at = NOW()
            WHERE appointment_id = :aid AND practice_id = :pid
        """),
        {
            "rating": rating,
            "feedback": feedback[:2000],
            "aid": appointment_id,
            "pid": practice_id,
        },
    )
    await db.commit()

    # Check if we should prompt for Google review
    config_result = await db.execute(
        text("SELECT config FROM practices WHERE id = :pid"),
        {"pid": practice_id},
    )
    config_row = config_result.fetchone()
    practice_config = config_row.config if config_row and config_row.config else {}
    survey_config = _get_survey_config(practice_config)

    result_data = {
        "appointment_id": appointment_id,
        "rating": rating,
        "feedback_saved": bool(feedback),
        "google_review_prompted": False,
    }

    if (
        survey_config["include_google_review"]
        and survey_config["google_review_url"]
        and rating >= survey_config["min_rating_for_review"]
    ):
        # Get patient phone for follow-up
        survey_row = await db.execute(
            text("SELECT patient_phone FROM surveys WHERE appointment_id = :aid"),
            {"aid": appointment_id},
        )
        sr = survey_row.fetchone()
        if sr and sr.patient_phone:
            review_msg = (
                f"Thank you for the great rating! Would you mind leaving us a "
                f"Google review? {survey_config['google_review_url']}"
            )
            await _send_survey_sms(sr.patient_phone, review_msg, practice_id)
            result_data["google_review_prompted"] = True

    return result_data


async def get_survey_stats(
    db: AsyncSession, practice_id: str, period: str = "month"
) -> dict:
    """Get survey statistics for a practice."""
    if period == "week":
        interval = "7 days"
    else:
        interval = "30 days"

    result = await db.execute(
        text("""
            SELECT
                COUNT(*) AS total_sent,
                COUNT(rating) AS total_responded,
                COALESCE(AVG(rating), 0) AS avg_rating,
                COUNT(CASE WHEN rating = 5 THEN 1 END) AS promoters,
                COUNT(CASE WHEN rating = 4 THEN 1 END) AS passives,
                COUNT(CASE WHEN rating <= 3 AND rating >= 1 THEN 1 END) AS detractors
            FROM surveys
            WHERE practice_id = :pid
              AND created_at >= NOW() - :interval::interval
        """),
        {"pid": practice_id, "interval": interval},
    )
    row = result.fetchone()

    total_responded = row.total_responded or 0
    nps = 0.0
    if total_responded > 0:
        nps = round(
            ((row.promoters or 0) - (row.detractors or 0))
            / total_responded
            * 100,
            1,
        )

    response_rate = (
        round(total_responded / row.total_sent * 100, 1)
        if row.total_sent > 0
        else 0
    )

    return {
        "total_sent": row.total_sent or 0,
        "total_responded": total_responded,
        "avg_rating": round(float(row.avg_rating or 0), 2),
        "nps_score": nps,
        "response_rate": response_rate,
        "promoters": row.promoters or 0,
        "passives": row.passives or 0,
        "detractors": row.detractors or 0,
    }


async def schedule_surveys_for_completed_appointments(
    db: AsyncSession, practice_id: str
) -> int:
    """Find today's completed appointments and schedule surveys."""
    # Get practice survey config
    config_result = await db.execute(
        text("SELECT config FROM practices WHERE id = :pid"),
        {"pid": practice_id},
    )
    config_row = config_result.fetchone()
    practice_config = config_row.config if config_row and config_row.config else {}
    survey_config = _get_survey_config(practice_config)

    if not survey_config["enabled"]:
        return 0

    # Find completed appointments from today with no survey
    result = await db.execute(
        text("""
            SELECT a.id
            FROM appointments a
            WHERE a.practice_id = :pid
              AND a.status = 'completed'
              AND a.date = CURRENT_DATE
              AND NOT EXISTS (
                  SELECT 1 FROM surveys s WHERE s.appointment_id = a.id
              )
        """),
        {"pid": practice_id},
    )

    count = 0
    for row in result.fetchall():
        sent = await send_post_visit_survey(db, str(row.id))
        if sent:
            count += 1

    return count


# ---------------------------------------------------------------------------
# SMS helper
# ---------------------------------------------------------------------------

async def _send_survey_sms(
    phone: str, message: str, practice_id: str
) -> bool:
    """Send survey SMS via Twilio."""
    settings = get_settings()
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        logger.warning("Twilio not configured — survey SMS not sent")
        return False

    try:
        from twilio.rest import Client

        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.messages.create(
            body=message,
            from_=settings.TWILIO_PHONE_NUMBER,
            to=phone,
        )
        logger.info("Survey SMS sent to %s for practice %s", phone, practice_id)
        return True
    except Exception as e:
        logger.error("Failed to send survey SMS to %s: %s", phone, e)
        return False
