"""
Stedi Coordination of Benefits (COB) & MBI Lookup service.

Provides:
  - COB checks to detect primary/secondary payer relationships
  - Medicare Beneficiary Identifier (MBI) lookups via SSN or demographic-only
  - Combined eligibility + COB + MBI workflow for comprehensive insurance checks

All operations are practice-scoped for multi-tenant security.
Raw API responses are stored as JSONB for HIPAA audit trail.
"""

import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.practice import Practice
from app.models.practice_config import PracticeConfig
from app.utils.http_client import get_http_client

logger = logging.getLogger(__name__)

STEDI_COB_URL = (
    "https://healthcare.us.stedi.com/2024-04-01/coordination-of-benefits"
)
STEDI_ELIGIBILITY_URL = (
    "https://healthcare.us.stedi.com/2024-04-01/change/medicalnetwork/eligibility/v3"
)
STEDI_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

# MBI lookup payer IDs
MBI_PAYER_WITH_SSN = "MBILU"
MBI_PAYER_WITHOUT_SSN = "MBILUNOSSN"

# Table creation SQL -- executed lazily on first use
_COB_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS cob_checks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id UUID NOT NULL,
    patient_name TEXT NOT NULL,
    member_id TEXT,
    payer_id TEXT,
    has_multiple_coverage BOOLEAN DEFAULT FALSE,
    primary_payer_id TEXT,
    primary_payer_name TEXT,
    secondary_payer_id TEXT,
    secondary_payer_name TEXT,
    raw_response JSONB,
    checked_at TIMESTAMPTZ DEFAULT NOW()
);
"""

_MBI_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS mbi_lookups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id UUID NOT NULL,
    patient_name TEXT NOT NULL,
    mbi TEXT,
    lookup_type TEXT NOT NULL DEFAULT 'no_ssn',
    raw_response JSONB,
    looked_up_at TIMESTAMPTZ DEFAULT NOW()
);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_control_number() -> str:
    """Generate a cryptographically random 9-digit numeric string."""
    return str(secrets.randbelow(10**9)).zfill(9)


def _format_dob(dob) -> str:
    """Format a date of birth into YYYYMMDD for Stedi."""
    if hasattr(dob, "strftime"):
        return dob.strftime("%Y%m%d")
    return str(dob).replace("-", "")


async def _resolve_api_key(db: AsyncSession, practice_id: UUID) -> Optional[str]:
    """Resolve the Stedi API key: practice-level first, then global fallback."""
    settings = get_settings()

    from sqlalchemy import select
    stmt = select(PracticeConfig).where(PracticeConfig.practice_id == practice_id)
    result = await db.execute(stmt)
    practice_config = result.scalar_one_or_none()

    api_key = (
        (practice_config.stedi_api_key if practice_config else None)
        or settings.STEDI_API_KEY
    )
    return api_key or None


async def _ensure_tables(db: AsyncSession) -> None:
    """Create COB and MBI tables if they do not exist."""
    await db.execute(text(_COB_TABLE_SQL))
    await db.execute(text(_MBI_TABLE_SQL))


async def _get_practice(db: AsyncSession, practice_id: UUID) -> Optional[Practice]:
    """Fetch practice by ID."""
    from sqlalchemy import select
    stmt = select(Practice).where(Practice.id == practice_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# 1. Coordination of Benefits Check
# ---------------------------------------------------------------------------

async def check_cob(
    db: AsyncSession,
    practice_id: UUID,
    patient_first_name: str,
    patient_last_name: str,
    patient_dob,
    member_id: str,
    payer_id: str,
    provider_npi: str,
    provider_name: str,
    date_of_service: Optional[str] = None,
) -> dict:
    """Perform a Coordination of Benefits check via the Stedi API.

    Determines whether a patient has multiple insurance coverages and
    identifies primary/secondary payer relationships.

    Args:
        db: Async database session.
        practice_id: UUID of the practice (tenant scope).
        patient_first_name: Patient's first name.
        patient_last_name: Patient's last name.
        patient_dob: Patient's date of birth (date, datetime, or YYYY-MM-DD str).
        member_id: Insurance member/subscriber ID.
        payer_id: Stedi trading partner service ID.
        provider_npi: Rendering provider NPI.
        provider_name: Provider or organization name.
        date_of_service: Service date (YYYY-MM-DD). Defaults to today.

    Returns:
        {
            "has_multiple_coverage": bool,
            "primary_payer": dict | None,
            "secondary_payer": dict | None,
            "payer_details": list[dict],
            "error": str | None,
        }
    """
    await _ensure_tables(db)

    api_key = await _resolve_api_key(db, practice_id)
    if not api_key:
        logger.error("No Stedi API key for practice %s", practice_id)
        return {
            "has_multiple_coverage": False,
            "primary_payer": None,
            "secondary_payer": None,
            "payer_details": [],
            "error": "Stedi API key not configured",
        }

    dob_formatted = _format_dob(patient_dob)
    if date_of_service is None:
        date_of_service = datetime.now(timezone.utc).strftime("%Y%m%d")
    else:
        date_of_service = date_of_service.replace("-", "")

    control_number = _generate_control_number()
    patient_name = f"{patient_first_name.strip()} {patient_last_name.strip()}"

    payload = {
        "controlNumber": control_number,
        "tradingPartnerServiceId": payer_id,
        "provider": {
            "organizationName": provider_name,
            "npi": provider_npi,
        },
        "subscriber": {
            "firstName": patient_first_name.strip(),
            "lastName": patient_last_name.strip(),
            "dateOfBirth": dob_formatted,
            "memberId": member_id.strip(),
        },
        "encounter": {
            "dateOfService": date_of_service,
            "serviceTypeCode": "30",
        },
    }

    logger.info(
        "COB check for %s | payer=%s practice=%s control=%s",
        patient_name, payer_id, practice_id, control_number,
    )

    response_data: Optional[dict] = None
    error_message: Optional[str] = None

    try:
        client = get_http_client()
        response = await client.post(
            STEDI_COB_URL,
            json=payload,
            headers={
                "Authorization": f"Key {api_key}",
                "Content-Type": "application/json",
            },
            timeout=STEDI_TIMEOUT,
        )

        response_data = response.json()
        logger.debug("COB response status: %s", response.status_code)

        if response.status_code != 200:
            error_message = (
                f"Stedi COB API returned HTTP {response.status_code}: "
                f"{response_data.get('message', response.text[:200])}"
            )
            logger.error(error_message)

        if response_data and response_data.get("errors"):
            error_message = f"Stedi COB returned errors: {response_data['errors']}"
            logger.warning(error_message)

    except httpx.TimeoutException:
        error_message = "Stedi COB request timed out"
        logger.error("COB timeout for %s", patient_name)
    except httpx.HTTPError as exc:
        error_message = f"Stedi COB HTTP error: {exc}"
        logger.error("COB HTTP error for %s: %s", patient_name, exc)
    except Exception as exc:
        error_message = f"Unexpected error during COB check: {exc}"
        logger.exception("Unexpected COB error for %s", patient_name)

    # Parse the response
    has_multiple = False
    primary_payer = None
    secondary_payer = None
    payer_details: list[dict] = []

    if response_data and not error_message:
        has_multiple = bool(response_data.get("coverageOverlap", False))

        benefits = response_data.get("benefitsInformation") or []
        for benefit in benefits:
            payer_info = benefit.get("payer") or {}
            payer_entry = {
                "payer_id": payer_info.get("payerIdentification"),
                "payer_name": payer_info.get("payerName"),
                "coverage_type": benefit.get("code"),
                "coverage_description": benefit.get("name"),
                "primacy": benefit.get("coverageLevelCode"),
            }
            payer_details.append(payer_entry)

            # Identify primary and secondary payers
            primacy_code = (benefit.get("coverageLevelCode") or "").upper()
            if primacy_code in ("IND", "PRI", "P") and primary_payer is None:
                primary_payer = payer_entry
            elif primacy_code in ("SEC", "S") and secondary_payer is None:
                secondary_payer = payer_entry

        # If payerPrimacyDetermined but we did not find explicit codes,
        # treat the first and second entries as primary/secondary
        if response_data.get("payerPrimacyDetermined") and not primary_payer and payer_details:
            primary_payer = payer_details[0]
            if len(payer_details) > 1:
                secondary_payer = payer_details[1]

    # Persist to database
    try:
        await db.execute(
            text("""
                INSERT INTO cob_checks
                    (practice_id, patient_name, member_id, payer_id,
                     has_multiple_coverage, primary_payer_id, primary_payer_name,
                     secondary_payer_id, secondary_payer_name, raw_response)
                VALUES
                    (:practice_id, :patient_name, :member_id, :payer_id,
                     :has_multiple, :primary_id, :primary_name,
                     :secondary_id, :secondary_name, :raw_response)
            """),
            {
                "practice_id": str(practice_id),
                "patient_name": patient_name,
                "member_id": member_id.strip(),
                "payer_id": payer_id,
                "has_multiple": has_multiple,
                "primary_id": primary_payer.get("payer_id") if primary_payer else None,
                "primary_name": primary_payer.get("payer_name") if primary_payer else None,
                "secondary_id": secondary_payer.get("payer_id") if secondary_payer else None,
                "secondary_name": secondary_payer.get("payer_name") if secondary_payer else None,
                "raw_response": json.dumps(response_data) if response_data else None,
            },
        )
        await db.flush()
        logger.info("COB check saved for %s | multiple_coverage=%s", patient_name, has_multiple)
    except Exception as exc:
        logger.error("Failed to save COB check: %s", exc)

    return {
        "has_multiple_coverage": has_multiple,
        "primary_payer": primary_payer,
        "secondary_payer": secondary_payer,
        "payer_details": payer_details,
        "error": error_message,
    }


# ---------------------------------------------------------------------------
# 2. MBI (Medicare Beneficiary Identifier) Lookup
# ---------------------------------------------------------------------------

async def lookup_mbi(
    db: AsyncSession,
    practice_id: UUID,
    first_name: str,
    last_name: str,
    dob,
    state: str,
    provider_npi: str,
    provider_name: str,
    ssn: Optional[str] = None,
) -> dict:
    """Look up a patient's Medicare Beneficiary Identifier (MBI).

    Uses the Stedi eligibility endpoint with special payer IDs:
      - With SSN: tradingPartnerServiceId = 'MBILU'
      - Without SSN: tradingPartnerServiceId = 'MBILUNOSSN'

    Args:
        db: Async database session.
        practice_id: UUID of the practice (tenant scope).
        first_name: Patient's first name.
        last_name: Patient's last name.
        dob: Patient's date of birth.
        state: Patient's state of residence (2-letter code).
        provider_npi: Provider NPI.
        provider_name: Provider or organization name.
        ssn: Patient's Social Security Number (optional, omit dashes).

    Returns:
        {
            "found": bool,
            "mbi": str | None,
            "medicare_info": dict,
            "error": str | None,
        }
    """
    await _ensure_tables(db)

    api_key = await _resolve_api_key(db, practice_id)
    if not api_key:
        logger.error("No Stedi API key for practice %s", practice_id)
        return {
            "found": False,
            "mbi": None,
            "medicare_info": {},
            "error": "Stedi API key not configured",
        }

    dob_formatted = _format_dob(dob)
    control_number = _generate_control_number()
    patient_name = f"{first_name.strip()} {last_name.strip()}"

    # Determine lookup type and build subscriber
    if ssn:
        trading_partner = MBI_PAYER_WITH_SSN
        lookup_type = "ssn"
        subscriber = {
            "firstName": first_name.strip(),
            "lastName": last_name.strip(),
            "dateOfBirth": dob_formatted,
            "ssn": ssn.replace("-", "").strip(),
        }
    else:
        trading_partner = MBI_PAYER_WITHOUT_SSN
        lookup_type = "no_ssn"
        subscriber = {
            "firstName": first_name.strip(),
            "lastName": last_name.strip(),
            "dateOfBirth": dob_formatted,
            "address": {
                "state": state.strip().upper(),
            },
        }

    payload = {
        "controlNumber": control_number,
        "tradingPartnerServiceId": trading_partner,
        "provider": {
            "organizationName": provider_name,
            "npi": provider_npi,
        },
        "subscriber": subscriber,
        "encounter": {
            "serviceTypeCodes": ["30"],
        },
    }

    logger.info(
        "MBI lookup for %s | type=%s practice=%s control=%s",
        patient_name, lookup_type, practice_id, control_number,
    )

    response_data: Optional[dict] = None
    error_message: Optional[str] = None

    try:
        client = get_http_client()
        response = await client.post(
            STEDI_ELIGIBILITY_URL,
            json=payload,
            headers={
                "Authorization": f"Key {api_key}",
                "Content-Type": "application/json",
            },
            timeout=STEDI_TIMEOUT,
        )

        response_data = response.json()
        logger.debug("MBI response status: %s", response.status_code)

        if response.status_code != 200:
            error_message = (
                f"Stedi MBI API returned HTTP {response.status_code}: "
                f"{response_data.get('message', response.text[:200])}"
            )
            logger.error(error_message)

        if response_data and response_data.get("errors"):
            error_message = f"Stedi MBI returned errors: {response_data['errors']}"
            logger.warning(error_message)

    except httpx.TimeoutException:
        error_message = "Stedi MBI lookup timed out"
        logger.error("MBI timeout for %s", patient_name)
    except httpx.HTTPError as exc:
        error_message = f"Stedi MBI HTTP error: {exc}"
        logger.error("MBI HTTP error for %s: %s", patient_name, exc)
    except Exception as exc:
        error_message = f"Unexpected error during MBI lookup: {exc}"
        logger.exception("Unexpected MBI error for %s", patient_name)

    # Parse the response
    found = False
    mbi: Optional[str] = None
    medicare_info: dict = {}

    if response_data and not error_message:
        # MBI is returned in the subscriber section
        sub = response_data.get("subscriber") or {}
        mbi = sub.get("memberId") or sub.get("mbi")

        if mbi:
            found = True

        # Extract plan status for Medicare details
        plan_statuses = response_data.get("planStatus") or []
        if plan_statuses:
            first_status = plan_statuses[0]
            medicare_info = {
                "status": first_status.get("status"),
                "plan_details": first_status.get("planDetails"),
                "effective_date": first_status.get("effectiveDate"),
                "termination_date": first_status.get("terminationDate"),
            }

        # Extract benefits info for coverage details
        benefits = response_data.get("benefitsInformation") or []
        if benefits:
            medicare_info["benefits_count"] = len(benefits)
            medicare_info["coverage_types"] = [
                b.get("name") for b in benefits if b.get("name")
            ]

    # Persist to database
    try:
        await db.execute(
            text("""
                INSERT INTO mbi_lookups
                    (practice_id, patient_name, mbi, lookup_type, raw_response)
                VALUES
                    (:practice_id, :patient_name, :mbi, :lookup_type, :raw_response)
            """),
            {
                "practice_id": str(practice_id),
                "patient_name": patient_name,
                "mbi": mbi,
                "lookup_type": lookup_type,
                "raw_response": json.dumps(response_data) if response_data else None,
            },
        )
        await db.flush()
        logger.info("MBI lookup saved for %s | found=%s mbi=%s", patient_name, found, bool(mbi))
    except Exception as exc:
        logger.error("Failed to save MBI lookup: %s", exc)

    return {
        "found": found,
        "mbi": mbi,
        "medicare_info": medicare_info,
        "error": error_message,
    }


# ---------------------------------------------------------------------------
# 3. Full Insurance Check (Eligibility + COB + MBI)
# ---------------------------------------------------------------------------

async def full_insurance_check(
    db: AsyncSession,
    practice_id: UUID,
    patient_first_name: str,
    patient_last_name: str,
    patient_dob,
    member_id: str,
    payer_id: str,
    provider_npi: str,
    provider_name: str,
    patient_state: str = "",
    patient_ssn: Optional[str] = None,
    date_of_service: Optional[str] = None,
) -> dict:
    """Run a comprehensive insurance check: eligibility + COB + MBI (if Medicare).

    This is the recommended entry point for a thorough insurance verification.
    It sequences three operations:
      1. Standard eligibility check (270/271)
      2. Coordination of Benefits check
      3. MBI lookup (only if the payer appears to be Medicare)

    Args:
        db: Async database session.
        practice_id: UUID of the practice.
        patient_first_name: Patient's first name.
        patient_last_name: Patient's last name.
        patient_dob: Patient's date of birth.
        member_id: Insurance member ID.
        payer_id: Stedi trading partner service ID.
        provider_npi: Provider NPI.
        provider_name: Provider or organization name.
        patient_state: Patient state (for MBI lookup without SSN).
        patient_ssn: Patient SSN (for MBI lookup with SSN, optional).
        date_of_service: Service date (YYYY-MM-DD), defaults to today.

    Returns:
        {
            "eligibility": dict,   -- standard eligibility result
            "cob": dict,           -- COB check result
            "mbi": dict | None,    -- MBI lookup result (only for Medicare)
            "summary": {
                "is_active": bool,
                "has_multiple_coverage": bool,
                "primary_payer": str | None,
                "mbi": str | None,
            },
            "errors": list[str],
        }
    """
    from app.services.insurance_service import check_eligibility as run_eligibility

    errors: list[str] = []

    # Step 1: Eligibility check
    logger.info(
        "Full insurance check step 1/3: eligibility for %s %s",
        patient_first_name, patient_last_name,
    )

    # The eligibility check needs a patient_id; we use practice_id as a placeholder
    # since we are doing a standalone check outside of patient context
    practice = await _get_practice(db, practice_id)
    if not practice:
        return {
            "eligibility": {},
            "cob": {},
            "mbi": None,
            "summary": {
                "is_active": False,
                "has_multiple_coverage": False,
                "primary_payer": None,
                "mbi": None,
            },
            "errors": ["Practice not found"],
        }

    # We call the eligibility endpoint directly for the full check
    api_key = await _resolve_api_key(db, practice_id)
    eligibility_result: dict = {}

    if api_key:
        control_number = _generate_control_number()
        dob_formatted = _format_dob(patient_dob)

        elig_payload = {
            "controlNumber": control_number,
            "tradingPartnerServiceId": payer_id,
            "provider": {
                "organizationName": provider_name,
                "npi": provider_npi,
            },
            "subscriber": {
                "firstName": patient_first_name.strip(),
                "lastName": patient_last_name.strip(),
                "dateOfBirth": dob_formatted,
                "memberId": member_id.strip(),
            },
            "encounter": {
                "serviceTypeCodes": ["30"],
            },
        }

        try:
            client = get_http_client()
            response = await client.post(
                STEDI_ELIGIBILITY_URL,
                json=elig_payload,
                headers={
                    "Authorization": f"Key {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=STEDI_TIMEOUT,
            )
            resp_data = response.json()

            if response.status_code == 200 and not resp_data.get("errors"):
                plan_statuses = resp_data.get("planStatus") or []
                is_active = False
                if plan_statuses:
                    status_text = (plan_statuses[0].get("status") or "").lower()
                    is_active = "active" in status_text

                eligibility_result = {
                    "verified": True,
                    "is_active": is_active,
                    "plan_name": (plan_statuses[0].get("planDetails") if plan_statuses else None),
                    "raw_response": resp_data,
                }
            else:
                err_msg = resp_data.get("message") or f"HTTP {response.status_code}"
                eligibility_result = {"verified": False, "error": err_msg}
                errors.append(f"Eligibility: {err_msg}")

        except Exception as exc:
            eligibility_result = {"verified": False, "error": str(exc)}
            errors.append(f"Eligibility: {exc}")
            logger.error("Full check eligibility error: %s", exc)
    else:
        eligibility_result = {"verified": False, "error": "No API key configured"}
        errors.append("No Stedi API key configured")

    # Step 2: COB check
    logger.info(
        "Full insurance check step 2/3: COB for %s %s",
        patient_first_name, patient_last_name,
    )
    cob_result = await check_cob(
        db=db,
        practice_id=practice_id,
        patient_first_name=patient_first_name,
        patient_last_name=patient_last_name,
        patient_dob=patient_dob,
        member_id=member_id,
        payer_id=payer_id,
        provider_npi=provider_npi,
        provider_name=provider_name,
        date_of_service=date_of_service,
    )
    if cob_result.get("error"):
        errors.append(f"COB: {cob_result['error']}")

    # Step 3: MBI lookup (only for Medicare-related payers)
    medicare_payer_ids = {"CMS", "80314", "MCARE", "MEDICARE"}
    is_medicare = payer_id.upper() in medicare_payer_ids or "medicare" in payer_id.lower()

    mbi_result: Optional[dict] = None
    if is_medicare and patient_state:
        logger.info(
            "Full insurance check step 3/3: MBI lookup for %s %s",
            patient_first_name, patient_last_name,
        )
        mbi_result = await lookup_mbi(
            db=db,
            practice_id=practice_id,
            first_name=patient_first_name,
            last_name=patient_last_name,
            dob=patient_dob,
            state=patient_state,
            provider_npi=provider_npi,
            provider_name=provider_name,
            ssn=patient_ssn,
        )
        if mbi_result.get("error"):
            errors.append(f"MBI: {mbi_result['error']}")
    else:
        logger.info(
            "Full insurance check step 3/3: MBI lookup skipped (payer=%s is not Medicare)",
            payer_id,
        )

    # Build summary
    summary = {
        "is_active": eligibility_result.get("is_active", False),
        "has_multiple_coverage": cob_result.get("has_multiple_coverage", False),
        "primary_payer": (
            cob_result.get("primary_payer", {}).get("payer_name")
            if cob_result.get("primary_payer")
            else None
        ),
        "mbi": mbi_result.get("mbi") if mbi_result else None,
    }

    logger.info(
        "Full insurance check complete for %s %s: active=%s multiple=%s mbi=%s errors=%d",
        patient_first_name, patient_last_name,
        summary["is_active"], summary["has_multiple_coverage"],
        bool(summary["mbi"]), len(errors),
    )

    return {
        "eligibility": eligibility_result,
        "cob": cob_result,
        "mbi": mbi_result,
        "summary": summary,
        "errors": errors,
    }
