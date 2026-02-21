"""
EHR Integration API routes — connect, sync, and manage EHR connections.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_practice_admin
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ehr", tags=["EHR Integration"])


class EHRConnectRequest(BaseModel):
    ehr_type: str  # athenahealth, drchrono, medicscloud, fhir_generic
    credentials: dict  # EHR-specific credentials


class EHRSyncRequest(BaseModel):
    resource_type: str = "appointments"  # appointments, patients


@router.post("/connect")
async def connect_ehr(
    body: EHRConnectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Connect a practice to their EHR system."""
    practice_id = current_user.practice_id
    if not practice_id:
        raise HTTPException(status_code=400, detail="No practice associated")

    try:
        from app.ehr.adapter import get_adapter
        adapter = get_adapter(body.ehr_type)
        connected = await adapter.connect(body.credentials)

        if not connected:
            raise HTTPException(status_code=400, detail="Failed to connect to EHR")

        # Save connection info
        await db.execute(text("""
            INSERT INTO ehr_connections
                (id, practice_id, ehr_type, is_connected, connection_metadata, created_at)
            VALUES
                (gen_random_uuid(), :pid, :ehr_type, TRUE, :metadata::jsonb, NOW())
            ON CONFLICT (practice_id) DO UPDATE SET
                ehr_type = :ehr_type,
                is_connected = TRUE,
                connection_metadata = :metadata::jsonb,
                updated_at = NOW()
        """), {
            "pid": str(practice_id),
            "ehr_type": body.ehr_type,
            "metadata": "{}",
        })
        await db.commit()

        logger.info("EHR connected: practice=%s type=%s", practice_id, body.ehr_type)
        return {"success": True, "ehr_type": body.ehr_type, "message": "Connected successfully"}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("EHR connect failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to connect to EHR")


@router.get("/status")
async def ehr_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Get EHR connection status for the practice."""
    practice_id = current_user.practice_id
    if not practice_id:
        return {"connected": False}

    result = await db.execute(text("""
        SELECT ehr_type, is_connected, last_sync_at, sync_enabled, created_at
        FROM ehr_connections
        WHERE practice_id = :pid
    """), {"pid": str(practice_id)})
    row = result.fetchone()

    if not row:
        return {"connected": False}

    return {
        "connected": row.is_connected,
        "ehr_type": row.ehr_type,
        "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
        "sync_enabled": row.sync_enabled,
        "connected_since": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/sync-log")
async def ehr_sync_log(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """View recent sync log entries."""
    practice_id = current_user.practice_id
    if not practice_id:
        return {"logs": []}

    result = await db.execute(text("""
        SELECT id, direction, resource_type, resource_id, status,
               details, error_message, created_at
        FROM ehr_sync_log
        WHERE practice_id = :pid
        ORDER BY created_at DESC
        LIMIT :limit
    """), {"pid": str(practice_id), "limit": limit})

    return {
        "logs": [
            {
                "id": str(row.id),
                "direction": row.direction,
                "resource_type": row.resource_type,
                "status": row.status,
                "error_message": row.error_message,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in result.fetchall()
        ]
    }


@router.delete("/disconnect")
async def disconnect_ehr(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """Disconnect the EHR integration."""
    practice_id = current_user.practice_id
    if not practice_id:
        raise HTTPException(status_code=400, detail="No practice associated")

    await db.execute(text("""
        UPDATE ehr_connections SET is_connected = FALSE, updated_at = NOW()
        WHERE practice_id = :pid
    """), {"pid": str(practice_id)})
    await db.commit()

    return {"success": True, "message": "EHR disconnected"}


@router.get("/providers")
async def ehr_providers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_practice_admin),
):
    """List providers from connected EHR."""
    practice_id = current_user.practice_id
    if not practice_id:
        return {"providers": []}

    # Get EHR connection
    result = await db.execute(text("""
        SELECT ehr_type, connection_metadata FROM ehr_connections
        WHERE practice_id = :pid AND is_connected = TRUE
    """), {"pid": str(practice_id)})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=400, detail="No EHR connected")

    try:
        import json as _json
        from app.ehr.adapter import get_adapter

        # Parse stored credentials for reconnection
        metadata = {}
        if row.connection_metadata:
            try:
                metadata = (
                    _json.loads(row.connection_metadata)
                    if isinstance(row.connection_metadata, str)
                    else row.connection_metadata
                )
            except (ValueError, TypeError):
                pass

        adapter = get_adapter(row.ehr_type)
        connected = await adapter.connect(metadata)
        if not connected:
            raise HTTPException(status_code=502, detail="Cannot reach EHR — check credentials")

        providers = await adapter.get_providers()
        return {
            "providers": [
                {
                    "ehr_id": p.ehr_id,
                    "name": p.name,
                    "npi": p.npi,
                    "specialty": p.specialty,
                }
                for p in providers
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to fetch EHR providers: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch providers from EHR")
