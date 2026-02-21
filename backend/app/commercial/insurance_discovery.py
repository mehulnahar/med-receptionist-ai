"""
Stedi Insurance Discovery — find patient's insurance from demographics.

When a patient doesn't know their insurance details (common in voice calls),
this service searches by name + DOB to find active coverage.
"""

import logging
import secrets
from typing import Optional
from uuid import UUID

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

STEDI_DISCOVERY_URL = "https://healthcare.us.stedi.com/2024-04-01/change/medicalnetwork/eligibility/v3"
STEDI_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


async def discover_insurance(
    first_name: str,
    last_name: str,
    dob: str,
    practice_npi: str,
    practice_name: str,
    api_key: str = "",
) -> dict:
    """Attempt to discover a patient's insurance from demographics only.

    Uses Stedi's eligibility check with service type code 30 (Health Benefit Plan Coverage)
    and iterates through common payer IDs to find active coverage.

    Returns:
        {
            "found": bool,
            "carrier_name": str | None,
            "payer_id": str | None,
            "member_id": str | None,
            "plan_name": str | None,
            "is_active": bool,
            "error": str | None,
        }
    """
    settings = get_settings()
    key = api_key or settings.STEDI_API_KEY

    if not key:
        return {"found": False, "error": "Stedi API key not configured"}

    # Common payer IDs to check for insurance discovery
    # These cover ~80% of commercial insurance in the US
    common_payers = [
        ("00901", "Cigna"),
        ("62308", "UnitedHealthcare"),
        ("00580", "Aetna"),
        ("SX109", "Anthem BCBS"),
        ("36273", "Empire BCBS"),
        ("22254", "Emblem / GHI"),
        ("13551", "Oxford Health Plans"),
        ("80314", "Medicare Part B"),
        ("CMS", "Medicare"),
        ("SKME0", "Medicaid"),
        ("MCDNY", "Medicaid NY"),
    ]

    dob_formatted = dob.replace("-", "")

    # Use a single shared client for all payer checks (connection reuse)
    async with httpx.AsyncClient(timeout=STEDI_TIMEOUT) as client:
        for payer_id, carrier_name in common_payers:
            try:
                result = await _check_payer(
                    client=client,
                    payer_id=payer_id,
                    carrier_name=carrier_name,
                    first_name=first_name,
                    last_name=last_name,
                    dob=dob_formatted,
                    practice_npi=practice_npi,
                    practice_name=practice_name,
                    api_key=key,
                )
                if result and result.get("is_active"):
                    logger.info(
                        "Insurance discovered: %s (%s) for %s %s",
                        carrier_name, payer_id, first_name, last_name,
                    )
                    return {
                        "found": True,
                        "carrier_name": carrier_name,
                        "payer_id": payer_id,
                        "member_id": result.get("member_id"),
                        "plan_name": result.get("plan_name"),
                        "is_active": True,
                        "error": None,
                    }
            except Exception as e:
                logger.debug("Discovery check failed for %s: %s", carrier_name, e)
                continue

    return {
        "found": False,
        "carrier_name": None,
        "payer_id": None,
        "member_id": None,
        "plan_name": None,
        "is_active": False,
        "error": "No active insurance found for this patient",
    }


async def _check_payer(
    client: httpx.AsyncClient,
    payer_id: str,
    carrier_name: str,
    first_name: str,
    last_name: str,
    dob: str,
    practice_npi: str,
    practice_name: str,
    api_key: str,
) -> Optional[dict]:
    """Check a single payer for active coverage."""
    control_number = str(secrets.randbelow(10**9)).zfill(9)

    payload = {
        "controlNumber": control_number,
        "tradingPartnerServiceId": payer_id,
        "provider": {
            "organizationName": practice_name,
            "npi": practice_npi,
        },
        "subscriber": {
            "firstName": first_name.strip(),
            "lastName": last_name.strip(),
            "dateOfBirth": dob,
        },
        "encounter": {
            "serviceTypeCodes": ["30"],
        },
    }

    response = await client.post(
        STEDI_DISCOVERY_URL,
        json=payload,
        headers={
            "Authorization": f"Key {api_key}",
            "Content-Type": "application/json",
        },
    )

    if response.status_code != 200:
        return None

    data = response.json()

    # Check for errors in response
    if data.get("errors"):
        return None

    # Check plan status
    plan_statuses = data.get("planStatus") or []
    if not plan_statuses:
        return None

    first_status = plan_statuses[0]
    status_text = (first_status.get("status") or "").lower()
    if "active" not in status_text:
        return None

    # Extract member ID and plan info
    subscriber = data.get("subscriber") or {}
    member_id = subscriber.get("memberId")
    plan_name = first_status.get("planDetails")

    return {
        "is_active": True,
        "member_id": member_id,
        "plan_name": plan_name,
    }
