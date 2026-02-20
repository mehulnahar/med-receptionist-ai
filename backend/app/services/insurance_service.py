"""
Stedi insurance eligibility verification service.

Integrates with the Stedi Healthcare API for real-time 270/271 eligibility
checks. All operations are practice-scoped for multi-tenant security.
Uses flush/refresh pattern -- caller controls transaction commit.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.insurance_carrier import InsuranceCarrier
from app.models.insurance_verification import InsuranceVerification
from app.models.practice import Practice
from app.models.practice_config import PracticeConfig

logger = logging.getLogger(__name__)

STEDI_ELIGIBILITY_URL = (
    "https://healthcare.us.stedi.com/2024-04-01/change/medicalnetwork/eligibility/v3"
)
STEDI_TIMEOUT = httpx.Timeout(15.0, connect=5.0, pool=5.0)
SERVICE_TYPE_CODE_HEALTH_BENEFIT = "30"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_control_number() -> str:
    """Generate a cryptographically random 9-digit numeric string for the EDI control number."""
    return str(secrets.randbelow(10**9)).zfill(9)


def _format_dob_for_stedi(dob) -> str:
    """
    Format a date of birth into Stedi's expected YYYYMMDD string.

    Accepts ``datetime.date``, ``datetime.datetime``, or an already-formatted
    string.  Returns the date without dashes.
    """
    if hasattr(dob, "strftime"):
        return dob.strftime("%Y%m%d")
    # Already a string -- strip any dashes just in case
    return str(dob).replace("-", "")


# ---------------------------------------------------------------------------
# 1. Payer-ID resolution (fuzzy carrier-name matching)
# ---------------------------------------------------------------------------

PAYER_RESOLUTION_TIMEOUT_SECONDS = 10


async def resolve_payer_id(
    db: AsyncSession,
    practice_id: UUID,
    carrier_name: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    Resolve a spoken / typed carrier name to a Stedi ``payer_id``.

    Strategy (evaluated in order):
      1. Exact (case-insensitive) match on ``insurance_carriers.name``.
      2. Check whether *carrier_name* appears inside any carrier's ``aliases``
         JSON array (case-insensitive substring comparison).
      3. Partial ``ILIKE`` match on the carrier name column.

    Returns ``(payer_id, matched_carrier_name)`` or ``(None, None)`` when no
    match is found. The entire resolution is bounded by a timeout to prevent
    slow queries from blocking the caller.
    """
    import asyncio

    try:
        return await asyncio.wait_for(
            _resolve_payer_id_inner(db, practice_id, carrier_name),
            timeout=PAYER_RESOLUTION_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Payer resolution timed out after %ds for carrier '%s' in practice %s",
            PAYER_RESOLUTION_TIMEOUT_SECONDS, carrier_name, practice_id,
        )
        return (None, None)


async def _resolve_payer_id_inner(
    db: AsyncSession,
    practice_id: UUID,
    carrier_name: str,
) -> tuple[Optional[str], Optional[str]]:
    """Inner implementation of payer resolution (wrapped by timeout)."""
    carrier_lower = carrier_name.strip().lower()

    if not carrier_lower:
        return (None, None)

    # --- 1. Exact match on name (case-insensitive) ---
    stmt_exact = (
        select(InsuranceCarrier)
        .where(
            and_(
                InsuranceCarrier.practice_id == practice_id,
                InsuranceCarrier.is_active.is_(True),
                func.lower(InsuranceCarrier.name) == carrier_lower,
            )
        )
        .limit(1)
    )
    result = await db.execute(stmt_exact)
    carrier = result.scalar_one_or_none()

    if carrier and carrier.stedi_payer_id:
        logger.debug(
            "Payer resolved via exact match: '%s' -> %s",
            carrier.name,
            carrier.stedi_payer_id,
        )
        return (carrier.stedi_payer_id, carrier.name)

    # --- 2. Check aliases (in-memory comparison) ---
    stmt_all = (
        select(InsuranceCarrier)
        .where(
            and_(
                InsuranceCarrier.practice_id == practice_id,
                InsuranceCarrier.is_active.is_(True),
                InsuranceCarrier.stedi_payer_id.isnot(None),
            )
        )
    )
    result_all = await db.execute(stmt_all)
    all_carriers = list(result_all.scalars().all())

    for c in all_carriers:
        aliases = c.aliases or []
        for alias in aliases:
            if isinstance(alias, str) and alias.strip().lower() == carrier_lower:
                logger.debug(
                    "Payer resolved via alias match: '%s' (alias '%s') -> %s",
                    c.name,
                    alias,
                    c.stedi_payer_id,
                )
                return (c.stedi_payer_id, c.name)

    # --- 3. Partial ILIKE match on name ---
    stmt_partial = (
        select(InsuranceCarrier)
        .where(
            and_(
                InsuranceCarrier.practice_id == practice_id,
                InsuranceCarrier.is_active.is_(True),
                InsuranceCarrier.stedi_payer_id.isnot(None),
                InsuranceCarrier.name.ilike(
                    "%{}%".format(
                        carrier_name.strip()
                        .replace("\\", "\\\\")
                        .replace("%", "\\%")
                        .replace("_", "\\_")
                    )
                ),
            )
        )
        .limit(1)
    )
    result_partial = await db.execute(stmt_partial)
    carrier_partial = result_partial.scalar_one_or_none()

    if carrier_partial:
        logger.debug(
            "Payer resolved via partial match: '%s' -> %s",
            carrier_partial.name,
            carrier_partial.stedi_payer_id,
        )
        return (carrier_partial.stedi_payer_id, carrier_partial.name)

    logger.warning(
        "Could not resolve payer_id for carrier '%s' in practice %s",
        carrier_name,
        practice_id,
    )
    return (None, None)


# ---------------------------------------------------------------------------
# 2. Parse Stedi eligibility response
# ---------------------------------------------------------------------------

def parse_eligibility_response(response_data: dict) -> dict:
    """
    Parse a Stedi 270/271 eligibility response into a normalised dict.

    Returns::

        {
            "is_active": bool,
            "plan_name": str | None,
            "copay": Decimal | None,
            "group_number": str | None,
            "raw_benefits": list,
        }
    """
    is_active = False
    plan_name: Optional[str] = None
    copay: Optional[Decimal] = None
    group_number: Optional[str] = None
    raw_benefits: list = []

    # --- Plan status ---
    plan_statuses = response_data.get("planStatus") or []
    if plan_statuses:
        first_status = plan_statuses[0]
        status_text = (first_status.get("status") or "").lower()
        is_active = "active" in status_text

        # Plan name may live in planDetails on planStatus entries
        plan_name = first_status.get("planDetails") or None

    # --- Subscriber info ---
    subscriber = response_data.get("subscriber") or {}
    group_number = subscriber.get("groupNumber") or None

    # --- Benefits information ---
    benefits_info = response_data.get("benefitsInformation") or []
    raw_benefits = benefits_info

    # Look for copay: code == "A" or name == "Co-Payment", in-network preferred
    for benefit in benefits_info:
        code = (benefit.get("code") or "").upper()
        name = (benefit.get("name") or "").lower()
        in_network = (benefit.get("inPlanNetworkIndicatorCode") or "").upper()

        is_copay = code == "A" or "co-payment" in name

        if is_copay and in_network == "Y":
            amount_str = benefit.get("benefitAmount")
            if amount_str is not None:
                try:
                    copay = Decimal(str(amount_str))
                except (InvalidOperation, ValueError, TypeError):
                    logger.warning(
                        "Could not parse copay amount: %s", amount_str
                    )
            break  # prefer first in-network copay

    # If no in-network copay found, accept any copay entry
    if copay is None:
        for benefit in benefits_info:
            code = (benefit.get("code") or "").upper()
            name = (benefit.get("name") or "").lower()
            is_copay = code == "A" or "co-payment" in name

            if is_copay:
                amount_str = benefit.get("benefitAmount")
                if amount_str is not None:
                    try:
                        copay = Decimal(str(amount_str))
                    except (InvalidOperation, ValueError, TypeError):
                        logger.warning(
                            "Could not parse copay amount: %s", amount_str
                        )
                break

    # Fallback: try to extract plan_name from first benefit's planDetails
    if plan_name is None:
        for benefit in benefits_info:
            pd = benefit.get("planDetails")
            if pd:
                plan_name = pd
                break

    return {
        "is_active": is_active,
        "plan_name": plan_name,
        "copay": copay,
        "group_number": group_number,
        "raw_benefits": raw_benefits,
    }


# ---------------------------------------------------------------------------
# 3. Cached verification lookup
# ---------------------------------------------------------------------------

async def get_cached_verification(
    db: AsyncSession,
    practice_id: UUID,
    patient_id: UUID,
    carrier_name: str,
    max_age_hours: int = 24,
) -> Optional[InsuranceVerification]:
    """
    Return a recent *successful* verification for the same patient and carrier
    if one exists within ``max_age_hours``.  Returns ``None`` otherwise.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    stmt = (
        select(InsuranceVerification)
        .where(
            and_(
                InsuranceVerification.practice_id == practice_id,
                InsuranceVerification.patient_id == patient_id,
                func.lower(InsuranceVerification.carrier_name) == carrier_name.strip().lower(),
                InsuranceVerification.status == "success",
                InsuranceVerification.verified_at >= cutoff,
            )
        )
        .order_by(InsuranceVerification.verified_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# 4. Main eligibility check
# ---------------------------------------------------------------------------

async def check_eligibility(
    db: AsyncSession,
    practice_id: UUID,
    patient_id: UUID,
    carrier_name: str,
    member_id: str,
    first_name: str,
    last_name: str,
    dob,
    call_id: Optional[UUID] = None,
) -> dict:
    """
    Perform a real-time 270/271 insurance eligibility check via the Stedi API.

    Workflow:
      1. Resolve ``carrier_name`` to a Stedi payer ID.
      2. Return a cached result if a successful verification exists within 24 h.
      3. Build the Stedi request payload.
      4. POST to the Stedi eligibility endpoint.
      5. Parse the response and persist the verification record.
      6. Return a normalised result dict.

    On network timeout or any API error the function saves a ``failed`` record
    and returns a graceful fallback dict (``verified=False``).

    Returns::

        {
            "verified": bool,
            "is_active": bool,
            "plan_name": str | None,
            "copay": Decimal | None,
            "group_number": str | None,
            "carrier": str | None,
            "member_id": str,
            "error": str | None,
        }
    """
    settings = get_settings()

    # --- 1. Resolve payer ID ---
    payer_id, matched_carrier = await resolve_payer_id(db, practice_id, carrier_name)

    if not payer_id:
        logger.warning(
            "No payer_id resolved for carrier '%s' -- cannot verify eligibility",
            carrier_name,
        )
        return {
            "verified": False,
            "is_active": False,
            "plan_name": None,
            "copay": None,
            "group_number": None,
            "carrier": carrier_name,
            "member_id": member_id,
            "error": f"Unknown insurance carrier: {carrier_name}",
        }

    # --- 2. Check cache ---
    cached = await get_cached_verification(db, practice_id, patient_id, carrier_name)
    if cached:
        logger.info(
            "Returning cached verification %s for patient %s (carrier=%s)",
            cached.id,
            patient_id,
            carrier_name,
        )
        return {
            "verified": True,
            "is_active": cached.is_active or False,
            "plan_name": cached.plan_name,
            "copay": cached.copay,
            "group_number": (cached.response_payload or {}).get("subscriber", {}).get("groupNumber"),
            "carrier": cached.carrier_name,
            "member_id": cached.member_id or member_id,
            "error": None,
        }

    # --- 3. Fetch practice info ---
    practice_stmt = select(Practice).where(Practice.id == practice_id)
    practice_result = await db.execute(practice_stmt)
    practice = practice_result.scalar_one_or_none()

    if not practice:
        return {
            "verified": False,
            "is_active": False,
            "plan_name": None,
            "copay": None,
            "group_number": None,
            "carrier": matched_carrier,
            "member_id": member_id,
            "error": "Practice not found",
        }

    # --- 4. Determine API key (practice-level, then global) ---
    config_stmt = select(PracticeConfig).where(
        PracticeConfig.practice_id == practice_id
    )
    config_result = await db.execute(config_stmt)
    practice_config = config_result.scalar_one_or_none()

    api_key = (
        (practice_config.stedi_api_key if practice_config else None)
        or settings.STEDI_API_KEY
    )

    if not api_key:
        logger.error("No Stedi API key configured for practice %s", practice_id)
        return {
            "verified": False,
            "is_active": False,
            "plan_name": None,
            "copay": None,
            "group_number": None,
            "carrier": matched_carrier,
            "member_id": member_id,
            "error": "Insurance verification not configured (missing API key)",
        }

    # --- 5. Build request payload ---
    control_number = _generate_control_number()
    dob_formatted = _format_dob_for_stedi(dob)

    request_payload = {
        "controlNumber": control_number,
        "tradingPartnerServiceId": payer_id,
        "provider": {
            "organizationName": practice.name,
            "npi": practice.npi,
        },
        "subscriber": {
            "firstName": first_name.strip(),
            "lastName": last_name.strip(),
            "dateOfBirth": dob_formatted,
            "memberId": member_id.strip(),
        },
        "encounter": {
            "serviceTypeCodes": [SERVICE_TYPE_CODE_HEALTH_BENEFIT],
        },
    }

    logger.info(
        "Stedi eligibility request for patient %s | carrier=%s payer=%s control=%s",
        patient_id,
        matched_carrier,
        payer_id,
        control_number,
    )
    logger.debug("Stedi request payload: %s", request_payload)

    # --- 6. Call Stedi API ---
    response_data: Optional[dict] = None
    error_message: Optional[str] = None

    try:
        from app.utils.http_client import get_http_client
        client = get_http_client()
        response = await client.post(
            STEDI_ELIGIBILITY_URL,
            json=request_payload,
            headers={
                "Authorization": f"Key {api_key}",
                "Content-Type": "application/json",
            },
            timeout=STEDI_TIMEOUT,
        )

        logger.debug("Stedi response status: %s", response.status_code)
        response_data = response.json()
        logger.debug("Stedi response body: %s", response_data)

        if response.status_code != 200:
            error_message = (
                f"Stedi API returned HTTP {response.status_code}: "
                f"{response_data.get('message') or response.text[:200]}"
            )
            logger.error(error_message)

        # Check for application-level errors in the response body
        if response_data and response_data.get("errors"):
            errors = response_data["errors"]
            error_message = f"Stedi returned errors: {errors}"
            logger.warning(error_message)

    except httpx.TimeoutException:
        error_message = "Stedi API request timed out"
        logger.error(
            "Stedi eligibility timeout after %.0fs for patient %s",
            STEDI_TIMEOUT.read,
            patient_id,
        )
    except httpx.HTTPError as exc:
        error_message = f"Stedi API HTTP error: {exc}"
        logger.error("Stedi HTTP error for patient %s: %s", patient_id, exc)
    except Exception as exc:
        error_message = f"Unexpected error during eligibility check: {exc}"
        logger.exception(
            "Unexpected error calling Stedi for patient %s", patient_id
        )

    # --- 7. Parse response ---
    parsed = {"is_active": False, "plan_name": None, "copay": None, "group_number": None, "raw_benefits": []}
    if response_data and not error_message:
        parsed = parse_eligibility_response(response_data)

    status = "success" if (response_data and not error_message) else "failed"

    # --- 8. Persist verification record ---
    verification = InsuranceVerification(
        practice_id=practice_id,
        patient_id=patient_id,
        call_id=call_id,
        carrier_name=matched_carrier,
        member_id=member_id.strip(),
        payer_id=payer_id,
        request_payload=request_payload,
        response_payload=response_data,
        is_active=parsed["is_active"],
        copay=parsed["copay"],
        plan_name=parsed["plan_name"],
        status=status,
    )
    db.add(verification)
    await db.flush()
    await db.refresh(verification)

    logger.info(
        "Insurance verification %s saved: status=%s is_active=%s copay=%s",
        verification.id,
        status,
        parsed["is_active"],
        parsed["copay"],
    )

    # --- 9. Build result ---
    return {
        "verified": status == "success",
        "is_active": parsed["is_active"],
        "plan_name": parsed["plan_name"],
        "copay": parsed["copay"],
        "group_number": parsed["group_number"],
        "carrier": matched_carrier,
        "member_id": member_id,
        "error": error_message,
    }


# ---------------------------------------------------------------------------
# 5. Verification history
# ---------------------------------------------------------------------------

async def get_verification_history(
    db: AsyncSession,
    practice_id: UUID,
    patient_id: Optional[UUID] = None,
    limit: int = 20,
) -> list[InsuranceVerification]:
    """
    Query past insurance verification records for a practice, optionally
    filtered by patient.  Results are ordered by most recent first.
    """
    filters = [InsuranceVerification.practice_id == practice_id]

    if patient_id is not None:
        filters.append(InsuranceVerification.patient_id == patient_id)

    stmt = (
        select(InsuranceVerification)
        .where(and_(*filters))
        .order_by(InsuranceVerification.verified_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
