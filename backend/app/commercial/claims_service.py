"""
Stedi 837P Professional Claims Submission service.

Provides:
  - Professional claims (837P) submission via Stedi
  - Claim status tracking
  - Claims listing with filtering
  - Patient control number generation

All operations are practice-scoped for multi-tenant security.
Raw Stedi responses are stored as JSONB for HIPAA compliance and audit trail.
"""

import json
import logging
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.practice_config import PracticeConfig
from app.utils.http_client import get_http_client

logger = logging.getLogger(__name__)

STEDI_CLAIMS_URL = (
    "https://healthcare.us.stedi.com/2024-04-01/change/medicalnetwork/"
    "professionalclaims/v3/submission"
)
STEDI_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

_CLAIMS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id UUID NOT NULL,
    patient_name TEXT NOT NULL,
    payer_id TEXT,
    payer_name TEXT,
    claim_type TEXT NOT NULL DEFAULT '837P',
    patient_control_number TEXT NOT NULL,
    stedi_control_number TEXT,
    correlation_id TEXT,
    total_charge_amount NUMERIC(10, 2),
    diagnosis_codes TEXT[],
    service_lines JSONB,
    status TEXT NOT NULL DEFAULT 'submitted',
    stedi_response JSONB,
    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


async def _ensure_table(db: AsyncSession) -> None:
    """Create the claims table if it does not exist."""
    await db.execute(text(_CLAIMS_TABLE_SQL))


async def generate_patient_control_number(practice_id: UUID) -> str:
    """Generate a unique patient control number for claim tracking.

    Format: PCN-{practice_short}-{timestamp}-{random}
    The control number is max 20 chars to comply with EDI limits.

    Args:
        practice_id: UUID of the practice.

    Returns:
        Unique patient control number string.
    """
    # Use last 4 chars of practice UUID for brevity
    practice_short = str(practice_id).replace("-", "")[-4:].upper()
    timestamp = datetime.now(timezone.utc).strftime("%y%m%d%H%M")
    random_part = str(secrets.randbelow(10000)).zfill(4)
    pcn = f"{practice_short}{timestamp}{random_part}"

    # Ensure max 20 characters for EDI compliance
    return pcn[:20]


def _build_claim_payload(
    claim_data: dict,
    patient_control_number: str,
) -> dict:
    """Build the full Stedi 837P claim payload from simplified input.

    Transforms our internal claim_data format into the Stedi-expected
    Professional Claims submission payload.

    Args:
        claim_data: Simplified claim data dict (see submit_claim docstring).
        patient_control_number: Unique PCN for this claim.

    Returns:
        Stedi-formatted claim submission payload.
    """
    patient = claim_data["patient"]
    billing = claim_data["billing_provider"]
    diagnosis_codes = claim_data.get("diagnosis_codes", [])
    service_lines_input = claim_data.get("service_lines", [])
    payer_id = claim_data["payer_id"]

    # Build diagnosis list (ICD-10 codes)
    health_care_code_info = []
    for i, code in enumerate(diagnosis_codes):
        entry = {
            "diagnosisTypeCode": "ABK" if i == 0 else "ABF",
            "diagnosisCode": code.strip().replace(".", ""),
        }
        health_care_code_info.append(entry)

    # Build service lines
    service_lines = []
    for idx, line in enumerate(service_lines_input, start=1):
        service_date = line.get("service_date", "")
        if hasattr(service_date, "strftime"):
            service_date = service_date.strftime("%Y%m%d")
        else:
            service_date = str(service_date).replace("-", "")

        # Build diagnosis pointers (1-based indices into the diagnosis array)
        pointers = line.get("diagnosis_pointers", [1])

        svc_line = {
            "serviceLineNumber": str(idx),
            "professionalService": {
                "procedureIdentifier": "HC",
                "procedureCode": line["procedure_code"].strip(),
                "lineItemChargeAmount": str(line["charge_amount"]),
                "measurementUnit": "UN",
                "serviceUnitCount": str(line.get("units", 1)),
                "compositeDiagnosisCodePointers": {
                    "diagnosisCodePointers": [str(p) for p in pointers],
                },
            },
            "serviceDate": service_date,
        }

        # Add modifiers if present
        modifiers = line.get("modifiers", [])
        if modifiers:
            svc_line["professionalService"]["procedureModifiers"] = modifiers[:4]

        service_lines.append(svc_line)

    # Build patient address
    patient_address = patient.get("address", {})

    # Build billing provider address
    billing_address = billing.get("address", {})

    # Build the full Stedi payload
    payload = {
        "tradingPartnerServiceId": payer_id,
        "submitter": {
            "organizationName": billing["name"],
            "contactInformation": {
                "name": billing.get("contact", {}).get("name", billing["name"]),
                "phoneNumber": billing.get("contact", {}).get("phone", ""),
            },
        },
        "receiver": {
            "organizationName": claim_data.get("payer_name", payer_id),
        },
        "subscriber": {
            "memberId": patient["memberId"],
            "paymentResponsibilityLevelCode": "P",
            "firstName": patient["firstName"],
            "lastName": patient["lastName"],
            "gender": patient.get("gender", "U"),
            "dateOfBirth": (
                patient["dob"].strftime("%Y%m%d")
                if hasattr(patient["dob"], "strftime")
                else str(patient["dob"]).replace("-", "")
            ),
            "address": {
                "address1": patient_address.get("address1", ""),
                "city": patient_address.get("city", ""),
                "state": patient_address.get("state", ""),
                "postalCode": patient_address.get("postalCode", ""),
            },
        },
        "billing": {
            "providerTaxonomy": billing.get("taxonomy_code", "207Q00000X"),
            "npi": billing["npi"],
            "taxId": billing["tax_id"],
            "organizationName": billing["name"],
            "address": {
                "address1": billing_address.get("address1", ""),
                "city": billing_address.get("city", ""),
                "state": billing_address.get("state", ""),
                "postalCode": billing_address.get("postalCode", ""),
            },
        },
        "claimInformation": {
            "patientControlNumber": patient_control_number,
            "claimChargeAmount": str(
                sum(
                    Decimal(str(sl.get("charge_amount", 0)))
                    for sl in service_lines_input
                )
            ),
            "placeOfServiceCode": claim_data.get("place_of_service_code", "11"),
            "claimFrequencyCode": claim_data.get("claim_frequency_code", "1"),
            "signatureIndicator": "Y",
            "planParticipationCode": "A",
            "benefitsAssignmentCertificationIndicator": "Y",
            "releaseOfInformationCode": "Y",
            "healthCareDiagnosisCode": health_care_code_info,
            "serviceLines": service_lines,
        },
    }

    # Add group number if available
    group_number = patient.get("groupNumber")
    if group_number:
        payload["subscriber"]["groupNumber"] = group_number

    return payload


# ---------------------------------------------------------------------------
# 1. Submit Claim
# ---------------------------------------------------------------------------

async def submit_claim(
    db: AsyncSession,
    practice_id: UUID,
    claim_data: dict,
) -> dict:
    """Submit a professional claim (837P) via the Stedi API.

    Args:
        db: Async database session.
        practice_id: UUID of the practice (tenant scope).
        claim_data: Simplified claim data with the following structure:
            {
                "payer_id": str,              -- Stedi trading partner ID
                "payer_name": str,            -- Payer display name (optional)
                "patient": {
                    "firstName": str,
                    "lastName": str,
                    "dob": str | date,        -- YYYY-MM-DD or date obj
                    "gender": str,            -- "M", "F", "U"
                    "memberId": str,
                    "groupNumber": str,       -- optional
                    "address": {
                        "address1": str,
                        "city": str,
                        "state": str,
                        "postalCode": str,
                    }
                },
                "billing_provider": {
                    "npi": str,
                    "tax_id": str,
                    "taxonomy_code": str,     -- optional, defaults to 207Q00000X
                    "name": str,
                    "address": {
                        "address1": str,
                        "city": str,
                        "state": str,
                        "postalCode": str,
                    },
                    "contact": {              -- optional
                        "name": str,
                        "phone": str,
                    }
                },
                "diagnosis_codes": [str],     -- ICD-10 codes
                "service_lines": [
                    {
                        "procedure_code": str,
                        "charge_amount": float | str,
                        "service_date": str | date,
                        "units": int,         -- defaults to 1
                        "diagnosis_pointers": [int],  -- 1-based indices
                        "modifiers": [str],   -- optional, max 4
                    }
                ],
                "place_of_service_code": str, -- defaults to "11" (Office)
                "claim_frequency_code": str,  -- defaults to "1" (Original)
            }

    Returns:
        {
            "success": bool,
            "claim_id": str | None,      -- local UUID
            "control_number": str,       -- patient control number
            "stedi_control_number": str | None,
            "correlation_id": str | None,
            "status": str,
            "error": str | None,
        }
    """
    await _ensure_table(db)

    api_key = await _resolve_api_key(db, practice_id)
    if not api_key:
        logger.error("No Stedi API key for practice %s", practice_id)
        return {
            "success": False,
            "claim_id": None,
            "control_number": None,
            "stedi_control_number": None,
            "correlation_id": None,
            "status": "error",
            "error": "Stedi API key not configured",
        }

    # Validate required fields
    required_keys = ["payer_id", "patient", "billing_provider", "diagnosis_codes", "service_lines"]
    for key in required_keys:
        if key not in claim_data or not claim_data[key]:
            return {
                "success": False,
                "claim_id": None,
                "control_number": None,
                "stedi_control_number": None,
                "correlation_id": None,
                "status": "error",
                "error": f"Missing required field: {key}",
            }

    patient = claim_data["patient"]
    for field in ["firstName", "lastName", "dob", "memberId"]:
        if field not in patient or not patient[field]:
            return {
                "success": False,
                "claim_id": None,
                "control_number": None,
                "stedi_control_number": None,
                "correlation_id": None,
                "status": "error",
                "error": f"Missing required patient field: {field}",
            }

    billing = claim_data["billing_provider"]
    for field in ["npi", "tax_id", "name"]:
        if field not in billing or not billing[field]:
            return {
                "success": False,
                "claim_id": None,
                "control_number": None,
                "stedi_control_number": None,
                "correlation_id": None,
                "status": "error",
                "error": f"Missing required billing_provider field: {field}",
            }

    # Generate a patient control number
    pcn = await generate_patient_control_number(practice_id)

    # Calculate total charge amount
    total_charge = sum(
        Decimal(str(sl.get("charge_amount", 0)))
        for sl in claim_data["service_lines"]
    )

    # Build the Stedi payload
    stedi_payload = _build_claim_payload(claim_data, pcn)

    patient_name = f"{patient['firstName']} {patient['lastName']}"
    payer_id = claim_data["payer_id"]
    payer_name = claim_data.get("payer_name", payer_id)

    logger.info(
        "Submitting 837P claim for %s | payer=%s practice=%s pcn=%s amount=%s",
        patient_name, payer_id, practice_id, pcn, total_charge,
    )

    response_data: Optional[dict] = None
    error_message: Optional[str] = None
    stedi_control: Optional[str] = None
    correlation_id: Optional[str] = None
    claim_status = "submitted"

    try:
        client = get_http_client()
        response = await client.post(
            STEDI_CLAIMS_URL,
            json=stedi_payload,
            headers={
                "Authorization": f"Key {api_key}",
                "Content-Type": "application/json",
            },
            timeout=STEDI_TIMEOUT,
        )

        response_data = response.json()
        logger.debug("Claims response status: %s", response.status_code)

        if response.status_code == 200 or response.status_code == 201:
            # Extract claim reference info
            claim_ref = response_data.get("claimReference") or {}
            stedi_control = response_data.get("controlNumber") or claim_ref.get("controlNumber")
            correlation_id = claim_ref.get("correlationId")

            api_status = (response_data.get("status") or "").lower()
            if api_status in ("accepted", "success"):
                claim_status = "accepted"
            elif api_status in ("rejected", "error"):
                claim_status = "rejected"
                error_message = response_data.get("message", "Claim rejected by payer")
            else:
                claim_status = "submitted"

        else:
            claim_status = "rejected"
            error_message = (
                f"Stedi Claims API returned HTTP {response.status_code}: "
                f"{response_data.get('message', response.text[:200])}"
            )
            logger.error(error_message)

        if response_data and response_data.get("errors"):
            claim_status = "rejected"
            error_message = f"Stedi Claims returned errors: {response_data['errors']}"
            logger.warning(error_message)

    except httpx.TimeoutException:
        claim_status = "error"
        error_message = "Stedi Claims API request timed out"
        logger.error("Claims timeout for %s", patient_name)
    except httpx.HTTPError as exc:
        claim_status = "error"
        error_message = f"Stedi Claims HTTP error: {exc}"
        logger.error("Claims HTTP error for %s: %s", patient_name, exc)
    except Exception as exc:
        claim_status = "error"
        error_message = f"Unexpected error during claims submission: {exc}"
        logger.exception("Unexpected claims error for %s", patient_name)

    # Persist claim to database
    claim_id: Optional[str] = None
    try:
        result = await db.execute(
            text("""
                INSERT INTO claims
                    (practice_id, patient_name, payer_id, payer_name, claim_type,
                     patient_control_number, stedi_control_number, correlation_id,
                     total_charge_amount, diagnosis_codes, service_lines,
                     status, stedi_response, submitted_at, updated_at)
                VALUES
                    (:practice_id, :patient_name, :payer_id, :payer_name, '837P',
                     :pcn, :stedi_control, :correlation_id,
                     :total_charge, :diagnosis_codes, :service_lines,
                     :status, :stedi_response, NOW(), NOW())
                RETURNING id
            """),
            {
                "practice_id": str(practice_id),
                "patient_name": patient_name,
                "payer_id": payer_id,
                "payer_name": payer_name,
                "pcn": pcn,
                "stedi_control": stedi_control,
                "correlation_id": correlation_id,
                "total_charge": float(total_charge),
                "diagnosis_codes": claim_data.get("diagnosis_codes", []),
                "service_lines": json.dumps(claim_data.get("service_lines", [])),
                "status": claim_status,
                "stedi_response": json.dumps(response_data) if response_data else None,
            },
        )
        row = result.fetchone()
        if row:
            claim_id = str(row.id)
        await db.flush()
        logger.info(
            "Claim %s saved: pcn=%s status=%s control=%s",
            claim_id, pcn, claim_status, stedi_control,
        )
    except Exception as exc:
        logger.error("Failed to save claim record: %s", exc)

    return {
        "success": claim_status in ("submitted", "accepted"),
        "claim_id": claim_id,
        "control_number": pcn,
        "stedi_control_number": stedi_control,
        "correlation_id": correlation_id,
        "status": claim_status,
        "error": error_message,
    }


# ---------------------------------------------------------------------------
# 2. Get Claim Status
# ---------------------------------------------------------------------------

async def get_claim_status(
    db: AsyncSession,
    practice_id: UUID,
    claim_id: str,
) -> dict:
    """Retrieve the current status and details of a claim.

    Args:
        db: Async database session.
        practice_id: UUID of the practice (tenant scope).
        claim_id: UUID of the claim record.

    Returns:
        Full claim details dict, or error dict if not found.
    """
    await _ensure_table(db)

    result = await db.execute(
        text("""
            SELECT
                id, practice_id, patient_name, payer_id, payer_name,
                claim_type, patient_control_number, stedi_control_number,
                correlation_id, total_charge_amount, diagnosis_codes,
                service_lines, status, stedi_response,
                submitted_at, updated_at
            FROM claims
            WHERE id = :claim_id AND practice_id = :practice_id
        """),
        {"claim_id": claim_id, "practice_id": str(practice_id)},
    )
    row = result.fetchone()

    if not row:
        logger.warning("Claim %s not found for practice %s", claim_id, practice_id)
        return {"error": "Claim not found", "claim_id": claim_id}

    return {
        "claim_id": str(row.id),
        "practice_id": str(row.practice_id),
        "patient_name": row.patient_name,
        "payer_id": row.payer_id,
        "payer_name": row.payer_name,
        "claim_type": row.claim_type,
        "patient_control_number": row.patient_control_number,
        "stedi_control_number": row.stedi_control_number,
        "correlation_id": row.correlation_id,
        "total_charge_amount": float(row.total_charge_amount) if row.total_charge_amount else None,
        "diagnosis_codes": row.diagnosis_codes or [],
        "service_lines": row.service_lines or [],
        "status": row.status,
        "stedi_response": row.stedi_response or {},
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ---------------------------------------------------------------------------
# 3. List Claims
# ---------------------------------------------------------------------------

async def list_claims(
    db: AsyncSession,
    practice_id: UUID,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List claims for a practice, optionally filtered by status.

    Args:
        db: Async database session.
        practice_id: UUID of the practice (tenant scope).
        status: Filter by claim status ('submitted', 'accepted', 'rejected',
            'denied', 'paid'). If None, returns all statuses.
        limit: Maximum number of claims to return (default 50).

    Returns:
        List of claim summary dicts, ordered by submission date descending.
    """
    await _ensure_table(db)

    # Clamp limit to reasonable bounds
    limit = max(1, min(limit, 500))

    if status:
        valid_statuses = {"submitted", "accepted", "rejected", "denied", "paid", "error"}
        if status not in valid_statuses:
            logger.warning("Invalid claim status filter: %s", status)
            return []

        result = await db.execute(
            text("""
                SELECT
                    id, patient_name, payer_id, payer_name, claim_type,
                    patient_control_number, stedi_control_number,
                    total_charge_amount, status, submitted_at, updated_at
                FROM claims
                WHERE practice_id = :practice_id AND status = :status
                ORDER BY submitted_at DESC
                LIMIT :limit
            """),
            {
                "practice_id": str(practice_id),
                "status": status,
                "limit": limit,
            },
        )
    else:
        result = await db.execute(
            text("""
                SELECT
                    id, patient_name, payer_id, payer_name, claim_type,
                    patient_control_number, stedi_control_number,
                    total_charge_amount, status, submitted_at, updated_at
                FROM claims
                WHERE practice_id = :practice_id
                ORDER BY submitted_at DESC
                LIMIT :limit
            """),
            {
                "practice_id": str(practice_id),
                "limit": limit,
            },
        )

    rows = result.fetchall()

    claims = []
    for row in rows:
        claims.append({
            "claim_id": str(row.id),
            "patient_name": row.patient_name,
            "payer_id": row.payer_id,
            "payer_name": row.payer_name,
            "claim_type": row.claim_type,
            "patient_control_number": row.patient_control_number,
            "stedi_control_number": row.stedi_control_number,
            "total_charge_amount": float(row.total_charge_amount) if row.total_charge_amount else None,
            "status": row.status,
            "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        })

    logger.debug(
        "Listed %d claims for practice %s (status=%s)",
        len(claims), practice_id, status or "all",
    )
    return claims
