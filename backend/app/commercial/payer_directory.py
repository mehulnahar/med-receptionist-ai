"""
Stedi Payer Directory — search, browse, and sync insurance payers.

Provides:
  - Payer search by name or ID
  - Detailed payer information retrieval
  - Local payer directory sync for offline/fast lookups
  - Filtered payer lists by supported transaction types

Uses the Stedi Payer Intelligence API. Results are cached locally in the
``payer_directory`` table for fast dashboard rendering.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.practice_config import PracticeConfig
from app.utils.http_client import get_http_client

logger = logging.getLogger(__name__)

STEDI_PAYERS_URL = "https://healthcare.us.stedi.com/2024-04-01/payers"
STEDI_PAYERS_SEARCH_URL = "https://healthcare.us.stedi.com/2024-04-01/payers/search"
STEDI_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

_PAYER_DIR_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS payer_directory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stedi_id TEXT NOT NULL,
    payer_id TEXT,
    display_name TEXT NOT NULL,
    avatar_url TEXT,
    coverage_types TEXT[],
    operating_states TEXT[],
    supports_eligibility BOOLEAN DEFAULT FALSE,
    supports_claims BOOLEAN DEFAULT FALSE,
    supports_cob BOOLEAN DEFAULT FALSE,
    enrollment_required BOOLEAN DEFAULT FALSE,
    synced_at TIMESTAMPTZ DEFAULT NOW(),
    practice_id UUID
);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_api_key(
    db: Optional[AsyncSession] = None,
    practice_id: Optional[UUID] = None,
    api_key: str = "",
) -> Optional[str]:
    """Resolve the Stedi API key: explicit > practice-level > global."""
    if api_key:
        return api_key

    settings = get_settings()

    if db and practice_id:
        from sqlalchemy import select
        stmt = select(PracticeConfig).where(PracticeConfig.practice_id == practice_id)
        result = await db.execute(stmt)
        config = result.scalar_one_or_none()
        if config and config.stedi_api_key:
            return config.stedi_api_key

    return settings.STEDI_API_KEY or None


async def _ensure_table(db: AsyncSession) -> None:
    """Create the payer_directory table if it does not exist."""
    await db.execute(text(_PAYER_DIR_TABLE_SQL))


# ---------------------------------------------------------------------------
# 1. Search Payers
# ---------------------------------------------------------------------------

async def search_payers(
    query: str,
    api_key: str = "",
) -> list[dict]:
    """Search the Stedi payer directory by name or payer ID.

    This function does NOT require a database session and can be called
    directly with an API key for lightweight lookups.

    Args:
        query: Search term (payer name, partial name, or payer ID).
        api_key: Stedi API key. Falls back to global config if empty.

    Returns:
        List of matching payer dicts, each with:
            {
                "stedi_id": str,
                "payer_id": str,
                "display_name": str,
                "avatar_url": str | None,
                "supports_eligibility": bool,
                "supports_claims": bool,
            }
    """
    resolved_key = await _resolve_api_key(api_key=api_key)
    if not resolved_key:
        logger.error("No Stedi API key available for payer search")
        return []

    if not query or not query.strip():
        logger.warning("Empty search query for payer directory")
        return []

    logger.info("Searching payer directory: query='%s'", query)

    try:
        client = get_http_client()
        response = await client.get(
            STEDI_PAYERS_SEARCH_URL,
            params={"query": query.strip()},
            headers={
                "Authorization": f"Key {resolved_key}",
            },
            timeout=STEDI_TIMEOUT,
        )

        if response.status_code != 200:
            logger.error(
                "Payer search failed: HTTP %s - %s",
                response.status_code, response.text[:200],
            )
            return []

        data = response.json()
        payers = data if isinstance(data, list) else data.get("payers", [])

        results = []
        for payer in payers:
            supported = payer.get("supportedTransactions") or {}
            results.append({
                "stedi_id": payer.get("stediId") or payer.get("id", ""),
                "payer_id": payer.get("payerId") or payer.get("tradingPartnerServiceId", ""),
                "display_name": payer.get("displayName") or payer.get("payerName", ""),
                "avatar_url": payer.get("avatarUrl"),
                "supports_eligibility": bool(supported.get("eligibilityCheck")),
                "supports_claims": bool(supported.get("professionalClaims")),
            })

        logger.info("Payer search returned %d results for query='%s'", len(results), query)
        return results

    except httpx.TimeoutException:
        logger.error("Payer search timed out for query='%s'", query)
        return []
    except httpx.HTTPError as exc:
        logger.error("Payer search HTTP error: %s", exc)
        return []
    except Exception as exc:
        logger.exception("Unexpected error during payer search: %s", exc)
        return []


# ---------------------------------------------------------------------------
# 2. Get Payer Details
# ---------------------------------------------------------------------------

async def get_payer_details(
    stedi_id: str,
    api_key: str = "",
) -> dict:
    """Retrieve full details for a specific payer by Stedi ID.

    Args:
        stedi_id: The Stedi-assigned payer identifier.
        api_key: Stedi API key. Falls back to global config if empty.

    Returns:
        Full payer details dict including supported transactions,
        enrollment requirements, contact info, and operating states.
        Returns empty dict on error.
    """
    resolved_key = await _resolve_api_key(api_key=api_key)
    if not resolved_key:
        logger.error("No Stedi API key available for payer details")
        return {}

    if not stedi_id or not stedi_id.strip():
        logger.warning("Empty stedi_id for payer details lookup")
        return {}

    url = f"{STEDI_PAYERS_URL}/{stedi_id.strip()}"
    logger.info("Fetching payer details: stedi_id=%s", stedi_id)

    try:
        client = get_http_client()
        response = await client.get(
            url,
            headers={
                "Authorization": f"Key {resolved_key}",
            },
            timeout=STEDI_TIMEOUT,
        )

        if response.status_code == 404:
            logger.warning("Payer not found: stedi_id=%s", stedi_id)
            return {}

        if response.status_code != 200:
            logger.error(
                "Payer details failed: HTTP %s - %s",
                response.status_code, response.text[:200],
            )
            return {}

        data = response.json()
        logger.info("Payer details retrieved for %s", stedi_id)
        return data

    except httpx.TimeoutException:
        logger.error("Payer details timed out for stedi_id=%s", stedi_id)
        return {}
    except httpx.HTTPError as exc:
        logger.error("Payer details HTTP error: %s", exc)
        return {}
    except Exception as exc:
        logger.exception("Unexpected error fetching payer details: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# 3. Sync Payer Directory
# ---------------------------------------------------------------------------

async def sync_payer_directory(
    db: AsyncSession,
    practice_id: UUID,
) -> dict:
    """Sync the Stedi payer directory to the local database.

    Fetches the complete payer list from Stedi and upserts into the
    ``payer_directory`` table scoped to the given practice. Existing entries
    for the practice are replaced on each sync.

    Args:
        db: Async database session.
        practice_id: UUID of the practice.

    Returns:
        {
            "synced": int,       -- number of payers synced
            "errors": int,       -- number of payers that failed to insert
            "last_synced": str,  -- ISO timestamp
            "error": str | None, -- top-level error if sync failed entirely
        }
    """
    await _ensure_table(db)

    api_key = await _resolve_api_key(db=db, practice_id=practice_id)
    if not api_key:
        logger.error("No Stedi API key for practice %s", practice_id)
        return {
            "synced": 0,
            "errors": 0,
            "last_synced": None,
            "error": "Stedi API key not configured",
        }

    logger.info("Starting payer directory sync for practice %s", practice_id)

    # Fetch full payer list
    try:
        client = get_http_client()
        response = await client.get(
            STEDI_PAYERS_URL,
            headers={
                "Authorization": f"Key {api_key}",
            },
            timeout=httpx.Timeout(30.0, connect=5.0),  # Longer timeout for full list
        )

        if response.status_code != 200:
            error_msg = f"Stedi payer list returned HTTP {response.status_code}"
            logger.error(error_msg)
            return {"synced": 0, "errors": 0, "last_synced": None, "error": error_msg}

        data = response.json()
        payers = data if isinstance(data, list) else data.get("payers", [])

    except httpx.TimeoutException:
        logger.error("Payer directory fetch timed out for practice %s", practice_id)
        return {"synced": 0, "errors": 0, "last_synced": None, "error": "Request timed out"}
    except httpx.HTTPError as exc:
        logger.error("Payer directory fetch error: %s", exc)
        return {"synced": 0, "errors": 0, "last_synced": None, "error": str(exc)}
    except Exception as exc:
        logger.exception("Unexpected error fetching payer directory: %s", exc)
        return {"synced": 0, "errors": 0, "last_synced": None, "error": str(exc)}

    if not payers:
        logger.warning("Stedi returned empty payer list for practice %s", practice_id)
        return {"synced": 0, "errors": 0, "last_synced": None, "error": "Empty payer list"}

    # Clear existing entries for this practice before re-syncing
    await db.execute(
        text("DELETE FROM payer_directory WHERE practice_id = :pid"),
        {"pid": str(practice_id)},
    )

    now = datetime.now(timezone.utc)
    synced_count = 0
    error_count = 0

    for payer in payers:
        try:
            supported = payer.get("supportedTransactions") or {}
            stedi_id = payer.get("stediId") or payer.get("id", "")
            payer_id = payer.get("payerId") or payer.get("tradingPartnerServiceId", "")
            display_name = payer.get("displayName") or payer.get("payerName", "Unknown")

            # Extract coverage types and operating states
            coverage_types = payer.get("coverageTypes") or []
            operating_states = payer.get("operatingStates") or []

            # Normalize lists to arrays of strings
            if isinstance(coverage_types, list):
                coverage_types = [str(ct) for ct in coverage_types]
            else:
                coverage_types = []

            if isinstance(operating_states, list):
                operating_states = [str(st) for st in operating_states]
            else:
                operating_states = []

            enrollment_info = payer.get("enrollment") or {}
            enrollment_required = bool(enrollment_info.get("required", False))

            await db.execute(
                text("""
                    INSERT INTO payer_directory
                        (practice_id, stedi_id, payer_id, display_name, avatar_url,
                         coverage_types, operating_states, supports_eligibility,
                         supports_claims, supports_cob, enrollment_required, synced_at)
                    VALUES
                        (:practice_id, :stedi_id, :payer_id, :display_name, :avatar_url,
                         :coverage_types, :operating_states, :supports_elig,
                         :supports_claims, :supports_cob, :enrollment_required, :synced_at)
                """),
                {
                    "practice_id": str(practice_id),
                    "stedi_id": stedi_id,
                    "payer_id": payer_id,
                    "display_name": display_name,
                    "avatar_url": payer.get("avatarUrl"),
                    "coverage_types": coverage_types,
                    "operating_states": operating_states,
                    "supports_elig": bool(supported.get("eligibilityCheck")),
                    "supports_claims": bool(supported.get("professionalClaims")),
                    "supports_cob": bool(supported.get("coordinationOfBenefits")),
                    "enrollment_required": enrollment_required,
                    "synced_at": now,
                },
            )
            synced_count += 1
        except Exception as exc:
            error_count += 1
            logger.warning("Failed to sync payer %s: %s", payer.get("stediId", "?"), exc)

    await db.flush()
    logger.info(
        "Payer directory sync complete for practice %s: synced=%d errors=%d",
        practice_id, synced_count, error_count,
    )

    return {
        "synced": synced_count,
        "errors": error_count,
        "last_synced": now.isoformat(),
        "error": None,
    }


# ---------------------------------------------------------------------------
# 4. Get Supported Payers (from local cache)
# ---------------------------------------------------------------------------

async def get_supported_payers(
    db: AsyncSession,
    practice_id: UUID,
    transaction_type: str = "eligibilityCheck",
) -> list[dict]:
    """Return payers that support a given transaction type from the local cache.

    Args:
        db: Async database session.
        practice_id: UUID of the practice.
        transaction_type: One of 'eligibilityCheck', 'professionalClaims', 'cob'.
            Defaults to 'eligibilityCheck'.

    Returns:
        List of payer dicts matching the criteria, sorted by display name.
    """
    await _ensure_table(db)

    # Map transaction_type to the corresponding column
    column_map = {
        "eligibilityCheck": "supports_eligibility",
        "eligibility": "supports_eligibility",
        "professionalClaims": "supports_claims",
        "claims": "supports_claims",
        "cob": "supports_cob",
        "coordinationOfBenefits": "supports_cob",
    }

    column = column_map.get(transaction_type)
    if not column:
        logger.warning("Unknown transaction_type: %s", transaction_type)
        return []

    # Use parameterized query with the column name injected safely
    # (column comes from our own map, not user input)
    query = f"""
        SELECT
            stedi_id, payer_id, display_name, avatar_url,
            coverage_types, operating_states,
            supports_eligibility, supports_claims, supports_cob,
            enrollment_required, synced_at
        FROM payer_directory
        WHERE practice_id = :pid AND {column} = TRUE
        ORDER BY display_name ASC
    """

    result = await db.execute(text(query), {"pid": str(practice_id)})
    rows = result.fetchall()

    payers = []
    for row in rows:
        payers.append({
            "stedi_id": row.stedi_id,
            "payer_id": row.payer_id,
            "display_name": row.display_name,
            "avatar_url": row.avatar_url,
            "coverage_types": row.coverage_types or [],
            "operating_states": row.operating_states or [],
            "supports_eligibility": row.supports_eligibility,
            "supports_claims": row.supports_claims,
            "supports_cob": row.supports_cob,
            "enrollment_required": row.enrollment_required,
            "synced_at": row.synced_at.isoformat() if row.synced_at else None,
        })

    logger.debug(
        "Returned %d payers supporting %s for practice %s",
        len(payers), transaction_type, practice_id,
    )
    return payers
