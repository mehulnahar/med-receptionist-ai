"""
Twilio Fallback TwiML Endpoint.

When Vapi (the primary voice webhook) fails to respond, Twilio invokes this
fallback URL to get TwiML instructions. The endpoint looks up the practice's
configured fallback_phone_number and returns a <Dial> to ring the office phone.

If the DB is also unreachable, it returns a polite "unavailable" message --
this endpoint must NEVER crash. No authentication is required because Twilio
must be able to reach it even when the rest of the backend is degraded.

Requirement: XFER-03
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.practice_config import PracticeConfig

logger = logging.getLogger(__name__)

router = APIRouter()

# --------------------------------------------------------------------------
# TwiML helpers
# --------------------------------------------------------------------------

UNAVAILABLE_TWIML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<Response>\n"
    '  <Say voice="alice">We\'re sorry, the office is temporarily unavailable. '
    "Please try again shortly.</Say>\n"
    "</Response>"
)


def _dial_twiml(fallback_number: str) -> str:
    """Return TwiML XML that connects the caller to *fallback_number*."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        '  <Say voice="alice">Please hold while we connect you to the office.</Say>\n'
        f'  <Dial timeout="30">{fallback_number}</Dial>\n'
        '  <Say voice="alice">We\'re sorry, the office is currently unavailable. '
        "Please try again later.</Say>\n"
        "</Response>"
    )


# --------------------------------------------------------------------------
# Endpoint
# --------------------------------------------------------------------------

@router.api_route("/twilio-fallback", methods=["GET", "POST"])
async def twilio_fallback(
    request: Request,
    phone_number_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    """Return TwiML XML for Twilio fallback when Vapi is unreachable.

    Twilio can call this as either GET or POST. The practice is resolved by:
    1. An explicit ``phone_number_id`` query param (Vapi phone number ID or
       Twilio phone number).
    2. Twilio's ``Called`` / ``To`` form params sent on POST fallback requests.
    """
    try:
        config: Optional[PracticeConfig] = None

        # --- Strategy 1: explicit query param ---
        if phone_number_id:
            stmt = select(PracticeConfig).where(
                or_(
                    PracticeConfig.vapi_phone_number_id == phone_number_id,
                    PracticeConfig.twilio_phone_number == phone_number_id,
                )
            )
            result = await db.execute(stmt)
            config = result.scalar_one_or_none()

        # --- Strategy 2: Twilio POST form params ---
        if config is None and request.method == "POST":
            try:
                form = await request.form()
                called = form.get("Called") or form.get("To")
                if called:
                    stmt = select(PracticeConfig).where(
                        PracticeConfig.twilio_phone_number == str(called)
                    )
                    result = await db.execute(stmt)
                    config = result.scalar_one_or_none()
            except Exception:
                # Form parsing may fail -- proceed with no config
                pass

        # --- Build response ---
        if config and config.fallback_phone_number:
            logger.warning(
                "twilio_fallback: Vapi down -- dialling fallback %s for practice %s",
                config.fallback_phone_number,
                config.practice_id,
            )
            twiml = _dial_twiml(config.fallback_phone_number)
        else:
            logger.warning(
                "twilio_fallback: Vapi down -- no fallback number found (phone_number_id=%s)",
                phone_number_id,
            )
            twiml = UNAVAILABLE_TWIML

        return PlainTextResponse(content=twiml, media_type="application/xml")

    except Exception:
        # DB might be down too -- return graceful message, never crash
        logger.exception("twilio_fallback: endpoint error -- returning unavailable TwiML")
        return PlainTextResponse(content=UNAVAILABLE_TWIML, media_type="application/xml")
