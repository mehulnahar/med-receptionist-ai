"""
pVerify insurance eligibility verification service.

Alternative to Stedi for real-time 270/271 eligibility checks.
Uses pVerify's REST API with OAuth2 authentication.
"""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.insurance_verification import InsuranceVerification
from app.models.practice_config import PracticeConfig

logger = logging.getLogger(__name__)

PVERIFY_AUTH_URL = "https://api.pverify.com/Token"
PVERIFY_ELIGIBILITY_URL = "https://api.pverify.com/api/EligibilitySummary"
PVERIFY_TIMEOUT = httpx.Timeout(20.0, connect=5.0, pool=5.0)

# Token cache (per practice)
_token_cache: dict[str, tuple[str, datetime]] = {}


async def _get_pverify_token(client_id: str, client_secret: str) -> Optional[str]:
    """Authenticate with pVerify OAuth2 and cache the token."""
    cache_key = f"{client_id}"
    cached = _token_cache.get(cache_key)
    if cached:
        token, expires_at = cached
        if expires_at > datetime.now(timezone.utc):
            return token

    try:
        async with httpx.AsyncClient(timeout=PVERIFY_TIMEOUT) as client:
            response = await client.post(
                PVERIFY_AUTH_URL,
                data={
                    "Client_Id": client_id,
                    "Client_Secret": client_secret,
                    "grant_type": "client_credentials",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            data = response.json()
            token = data.get("access_token")
            expires_in = int(data.get("expires_in", 3600))
            if token:
                _token_cache[cache_key] = (
                    token,
                    datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60),
                )
            return token
    except Exception as exc:
        logger.error("pVerify auth failed: %s", exc)
        return None


def _format_dob(dob) -> str:
    """Format DOB to MM/DD/YYYY for pVerify."""
    if hasattr(dob, "strftime"):
        return dob.strftime("%m/%d/%Y")
    s = str(dob).replace("-", "")
    if len(s) == 8:
        return f"{s[4:6]}/{s[6:8]}/{s[:4]}"
    return str(dob)


def parse_pverify_response(data: dict) -> dict:
    """Parse pVerify eligibility response into normalized format."""
    is_active = False
    plan_name = None
    copay = None
    group_number = None

    is_eligible = data.get("IsSubscriberEligible", False)
    is_active = is_eligible is True or str(is_eligible).lower() == "true"

    plan_name = data.get("PlanName") or data.get("InsuranceName")
    group_number = data.get("GroupNumber")

    copay_str = data.get("CopayAmount") or data.get("OVCopayInNet")
    if copay_str:
        try:
            copay = Decimal(str(copay_str).replace("$", "").replace(",", ""))
        except (InvalidOperation, ValueError):
            pass

    return {
        "is_active": is_active,
        "plan_name": plan_name,
        "copay": copay,
        "group_number": group_number,
        "raw_benefits": data.get("ServiceDetails", []),
    }


async def check_eligibility_pverify(
    db: AsyncSession,
    practice_id: UUID,
    patient_id: UUID,
    carrier_name: str,
    member_id: str,
    first_name: str,
    last_name: str,
    dob,
    payer_code: Optional[str] = None,
    call_id: Optional[UUID] = None,
) -> dict:
    """
    Perform real-time eligibility check via pVerify API.

    Returns same normalized dict format as Stedi service.
    """
    settings = get_settings()

    # Get practice-level or global credentials
    config_result = await db.execute(
        select(PracticeConfig).where(PracticeConfig.practice_id == practice_id)
    )
    config = config_result.scalar_one_or_none()

    client_id = (getattr(config, "pverify_client_id", None) if config else None) or settings.PVERIFY_CLIENT_ID
    client_secret = (getattr(config, "pverify_client_secret", None) if config else None) or settings.PVERIFY_CLIENT_SECRET

    if not client_id or not client_secret:
        return {
            "verified": False, "is_active": False, "plan_name": None,
            "copay": None, "group_number": None, "carrier": carrier_name,
            "member_id": member_id, "error": "pVerify not configured (missing credentials)",
        }

    # Authenticate
    token = await _get_pverify_token(client_id, client_secret)
    if not token:
        return {
            "verified": False, "is_active": False, "plan_name": None,
            "copay": None, "group_number": None, "carrier": carrier_name,
            "member_id": member_id, "error": "pVerify authentication failed",
        }

    # Build request
    dob_formatted = _format_dob(dob)
    request_payload = {
        "PayerCode": payer_code or "",
        "PayerName": carrier_name,
        "SubscriberMemberId": member_id.strip(),
        "SubscriberFirstName": first_name.strip(),
        "SubscriberLastName": last_name.strip(),
        "SubscriberDOB": dob_formatted,
        "isSubscriberPatient": "True",
        "DoS_StartDate": datetime.now().strftime("%m/%d/%Y"),
        "DoS_EndDate": datetime.now().strftime("%m/%d/%Y"),
    }

    logger.info("pVerify eligibility request for patient %s | carrier=%s", patient_id, carrier_name)

    response_data = None
    error_message = None

    try:
        from app.utils.http_client import get_http_client
        client = get_http_client()
        response = await client.post(
            PVERIFY_ELIGIBILITY_URL,
            json=request_payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Client-API-Id": client_id,
            },
            timeout=PVERIFY_TIMEOUT,
        )
        response_data = response.json()

        if response.status_code != 200:
            error_message = f"pVerify API returned HTTP {response.status_code}"

        api_status = response_data.get("APIResponseCode")
        if api_status and str(api_status) != "0":
            error_message = response_data.get("APIResponseMessage", "pVerify API error")

    except httpx.TimeoutException:
        error_message = "pVerify API request timed out"
    except Exception as exc:
        error_message = f"pVerify API error: {exc}"
        logger.exception("pVerify error for patient %s", patient_id)

    # Parse response
    parsed = {"is_active": False, "plan_name": None, "copay": None, "group_number": None, "raw_benefits": []}
    if response_data and not error_message:
        parsed = parse_pverify_response(response_data)

    status_str = "success" if (response_data and not error_message) else "failed"

    # Save verification record
    verification = InsuranceVerification(
        practice_id=practice_id,
        patient_id=patient_id,
        call_id=call_id,
        carrier_name=carrier_name,
        member_id=member_id.strip(),
        payer_id=payer_code,
        request_payload=request_payload,
        response_payload=response_data,
        is_active=parsed["is_active"],
        copay=parsed["copay"],
        plan_name=parsed["plan_name"],
        status=status_str,
    )
    db.add(verification)
    await db.flush()

    return {
        "verified": status_str == "success",
        "is_active": parsed["is_active"],
        "plan_name": parsed["plan_name"],
        "copay": parsed["copay"],
        "group_number": parsed["group_number"],
        "carrier": carrier_name,
        "member_id": member_id,
        "error": error_message,
    }
