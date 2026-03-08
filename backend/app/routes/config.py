"""Practice configuration endpoints."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.practice_config import PracticeConfig
from app.schemas.practice_config import PracticeConfigResponse, PracticeConfigUpdate
from app.middleware.auth import get_current_user, require_practice_admin, require_any_staff
from app.services.audit_service import log_audit
from app.services.vapi_service import sync_assistant_config
from app.utils.cache import practice_config_cache
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/", response_model=PracticeConfigResponse)
async def get_practice_config(
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Get the configuration for the current user's practice."""
    if not current_user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )

    result = await db.execute(
        select(PracticeConfig).where(
            PracticeConfig.practice_id == current_user.practice_id
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Practice configuration not found",
        )

    return PracticeConfigResponse.model_validate(config)


@router.put("/", response_model=PracticeConfigResponse)
async def update_practice_config(
    request: PracticeConfigUpdate,
    http_request: Request,
    current_user: User = Depends(require_practice_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update the configuration for the current user's practice (practice admin only)."""
    result = await db.execute(
        select(PracticeConfig).where(
            PracticeConfig.practice_id == current_user.practice_id
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Practice configuration not found",
        )

    update_data = request.model_dump(exclude_unset=True)

    # Never overwrite real encrypted secrets with masked placeholder values
    # that the frontend echoes back (e.g. "****abcd").
    SECRET_FIELDS = {
        "twilio_account_sid", "twilio_auth_token",
        "vapi_api_key", "stedi_api_key",
    }
    for field in SECRET_FIELDS:
        val = update_data.get(field)
        if val is not None and val.startswith("*"):
            del update_data[field]

    # Track if transfer_number is changing
    transfer_number_changed = (
        "transfer_number" in update_data
        and update_data["transfer_number"] != config.transfer_number
    )

    # Capture old values for audit (redact secrets)
    audit_old = {
        k: ("***REDACTED***" if k in SECRET_FIELDS else getattr(config, k, None))
        for k in update_data
    }

    for field, value in update_data.items():
        setattr(config, field, value)

    # HIPAA audit trail — redact secret values
    audit_new = {
        k: ("***REDACTED***" if k in SECRET_FIELDS else v)
        for k, v in update_data.items()
    }
    await log_audit(
        db, action="update_config", entity_type="practice_config",
        entity_id=config.id, user=current_user,
        old_value=audit_old, new_value=audit_new,
        request=http_request,
    )

    # Invalidate cache BEFORE commit — prevents a race where another request
    # reads the old DB row and re-populates the cache between commit and invalidate
    practice_config_cache.invalidate(f"practice_config:{current_user.practice_id}")

    await db.commit()
    await db.refresh(config)

    # Sync transfer number to Vapi assistant when it changes
    if transfer_number_changed and config.vapi_assistant_id:
        try:
            from app.services.vapi_service import update_assistant_transfer_number
            await update_assistant_transfer_number(
                assistant_id=config.vapi_assistant_id,
                transfer_number=config.transfer_number,
                transfer_message=config.transfer_message,
            )
        except Exception as e:
            logger.warning("Failed to sync transfer number to Vapi: %s", e)

    # ── Vapi config sync (prompt, voice, model, greeting) ──
    VAPI_SYNC_FIELDS = {
        "vapi_system_prompt", "vapi_first_message",
        "vapi_model_provider", "vapi_model_name",
        "vapi_voice_provider", "vapi_voice_id",
    }
    vapi_fields_changed = VAPI_SYNC_FIELDS & set(update_data.keys())
    sync_result = None

    if vapi_fields_changed and config.vapi_assistant_id:
        _settings = get_settings()
        api_key = config.vapi_api_key or _settings.VAPI_API_KEY
        if api_key:
            sync_result = await sync_assistant_config(
                assistant_id=config.vapi_assistant_id,
                vapi_api_key=config.vapi_api_key,
                system_prompt=update_data.get("vapi_system_prompt"),
                first_message=update_data.get("vapi_first_message"),
                model_provider=update_data.get("vapi_model_provider"),
                model_name=update_data.get("vapi_model_name"),
                voice_provider=update_data.get("vapi_voice_provider"),
                voice_id=update_data.get("vapi_voice_id"),
            )
            if sync_result and not sync_result["success"]:
                logger.warning(
                    "Vapi sync failed for practice %s: %s",
                    config.practice_id, sync_result["error"],
                )

    response = PracticeConfigResponse.model_validate(config)
    if vapi_fields_changed and sync_result:
        response.vapi_sync_status = sync_result
    return response
