"""
Vapi webhook route handler for the AI Medical Receptionist.

This single endpoint receives ALL Vapi webhook events and dispatches them
based on the message "type" field. Vapi sends every event to the same URL
as a POST with body: {"message": {"type": "...", ...}}.

Message types handled:
- assistant-request: Vapi asks for assistant configuration
- status-update: Call status changed (in-progress, ended, etc.)
- tool-calls: Vapi triggers tool functions (must respond with results)
- function-call: Legacy single function call format
- end-of-call-report: Call complete with transcript/recording/summary
- hang: Call hang notification

Security:
- HMAC signature verification via X-Vapi-Signature header when VAPI_WEBHOOK_SECRET is set
- Always returns 200 (even on errors) to prevent Vapi retries that cause bad UX
- Multi-tenant: resolves practice from the call's phone number (no unsafe fallback)
"""

import hashlib
import hmac
import json
import logging
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Request, Depends, Query, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.config import get_settings
from app.database import get_db
from app.models.call import Call
from app.models.patient import Patient
from app.models.user import User
from app.middleware.auth import require_any_staff
from app.schemas.call import CallResponse, CallListResponse, CallbackUpdateRequest, CallbackListResponse, CallStatsResponse
from app.schemas.vapi import (
    VapiWebhookRequest,
    VapiToolCallResponse,
    VapiToolCallResult,
)
from app.services.call_service import (
    create_or_update_call,
    update_call_status,
    save_end_of_call_report,
    resolve_practice_from_phone,
    get_practice_id_from_vapi_call,
)
from app.services.vapi_tools import dispatch_tool_call

logger = logging.getLogger(__name__)
router = APIRouter()


def _verify_vapi_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """
    Verify the HMAC-SHA256 signature sent by Vapi in the X-Vapi-Signature header.

    Returns True if signature is valid or if no secret is configured (graceful skip).
    Returns False if a secret is configured but signature is missing or invalid.
    """
    settings = get_settings()
    secret = settings.VAPI_WEBHOOK_SECRET

    if not secret:
        if settings.APP_ENV == "production":
            logger.error(
                "vapi_webhook: VAPI_WEBHOOK_SECRET is NOT set in production — "
                "rejecting ALL webhooks. Set the secret to accept Vapi events."
            )
            return False
        # Dev mode: skip verification with warning
        logger.warning("vapi_webhook: VAPI_WEBHOOK_SECRET not set — skipping signature check (dev mode)")
        return True

    if not signature_header:
        logger.warning("vapi_webhook: missing X-Vapi-Signature header — rejecting request")
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    if hmac.compare_digest(expected, signature_header):
        return True

    logger.warning("vapi_webhook: HMAC signature mismatch — rejecting request")
    return False


async def _run_feedback_analysis(call_id: UUID, practice_id: UUID):
    """Run feedback analysis in background with its own DB session.

    Retries up to 2 times with exponential backoff on transient failures.
    """
    import asyncio as _asyncio
    from app.database import AsyncSessionLocal
    from app.services.feedback_service import process_call_feedback

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            async with AsyncSessionLocal() as db:
                await process_call_feedback(db, call_id, practice_id)
                await db.commit()
            return
        except Exception as e:
            logger.warning(
                "background feedback analysis failed for call %s (attempt %d/%d): %s",
                call_id, attempt, max_attempts, e,
            )
            if attempt < max_attempts:
                await _asyncio.sleep(2 ** attempt)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_params(raw) -> dict:
    """Parse tool call parameters that may be a JSON string or dict."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    if isinstance(raw, dict):
        return raw
    return {}


def _safe_get(data: dict, *keys, default=None):
    """Safely traverse nested dicts without raising KeyError."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


async def _resolve_practice_id(
    db: AsyncSession,
    vapi_call_id: str | None,
    call_obj: dict | None,
) -> UUID | None:
    """
    Resolve the practice_id for this webhook event.

    Priority:
    1. Existing call record (by vapi_call_id) -- fastest path for mid-call events
    2. Phone number on the call object (the Vapi/Twilio number being called)
    3. Fallback: first active practice (single-client development phase)
    """
    # 1. Try existing call record
    if vapi_call_id:
        practice_id = await get_practice_id_from_vapi_call(db, vapi_call_id)
        if practice_id:
            return practice_id

    # 2. Try resolving from the phone number being called
    if call_obj:
        # Vapi includes the phone number config in different places
        phone_number = (
            _safe_get(call_obj, "phoneNumber", "number")
            or _safe_get(call_obj, "phoneNumber", "twilioPhoneNumber")
            or _safe_get(call_obj, "phoneNumber")
        )
        # phoneNumber might be a string (the number itself) or a dict
        if isinstance(phone_number, dict):
            phone_number = phone_number.get("number") or phone_number.get("twilioPhoneNumber")

        if phone_number and isinstance(phone_number, str):
            practice_id = await resolve_practice_from_phone(db, phone_number)
            if practice_id:
                return practice_id

    # 3. No fallback — reject unknown practices to prevent cross-tenant data leaks.
    #    In single-tenant mode, ensure the Vapi phone number is correctly
    #    configured in PracticeConfig so resolution works via step 2.
    logger.error(
        "_resolve_practice_id: could not resolve practice from call_id=%s or phone number. "
        "Ensure the Vapi phone number is configured in PracticeConfig.",
        vapi_call_id,
    )
    return None


# ---------------------------------------------------------------------------
# Main webhook endpoint
# ---------------------------------------------------------------------------

@router.post("/vapi")
async def vapi_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Receive ALL Vapi webhook events and dispatch by message type.

    Verifies HMAC signature if VAPI_WEBHOOK_SECRET is configured.
    Always returns 200 to prevent Vapi retries.
    """
    # ------------------------------------------------------------------
    # 0. Reject oversized payloads before any processing (DoS protection)
    # ------------------------------------------------------------------
    MAX_WEBHOOK_BODY_BYTES = 1_000_000  # 1 MB — well above typical Vapi payloads
    raw_body = await request.body()
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        logger.warning("vapi_webhook: rejected oversized payload (%d bytes)", len(raw_body))
        return JSONResponse(status_code=413, content={"error": "Payload too large"})

    # ------------------------------------------------------------------
    # 1. Verify webhook signature (if secret is configured)
    # ------------------------------------------------------------------
    signature = request.headers.get("x-vapi-signature")

    if not _verify_vapi_signature(raw_body, signature):
        logger.warning("vapi_webhook: signature verification failed — dropping request")
        # Return 200 to avoid leaking whether the endpoint exists or accepts traffic.
        # Returning 401/403 lets attackers enumerate valid webhook URLs.
        return JSONResponse(status_code=200, content={})

    # ------------------------------------------------------------------
    # 1. Parse raw body (for logging) then as typed schema
    # ------------------------------------------------------------------
    try:
        body = json.loads(raw_body)
    except Exception:
        logger.error("vapi_webhook: failed to parse JSON body (length=%d)", len(raw_body))
        return JSONResponse(status_code=200, content={})

    logger.info(
        "vapi_webhook: received type=%s",
        _safe_get(body, "message", "type", default="unknown"),
    )
    # NOTE: Do NOT log full body — it contains PHI (patient names, phone numbers,
    # insurance info, transcripts). Log only structural metadata.
    logger.debug(
        "vapi_webhook: keys=%s, call_id=%s",
        list(_safe_get(body, "message", default={}).keys()),
        _safe_get(body, "message", "call", "id", default="n/a"),
    )

    try:
        # Parse into typed model (allows extra fields for forward compat)
        webhook = VapiWebhookRequest.model_validate(body)
        message = webhook.message
    except Exception as e:
        logger.error("vapi_webhook: schema validation failed: %s", e)
        # Do NOT log body on validation failure — it may contain PHI
        logger.debug(
            "vapi_webhook: body type=%s, keys=%s",
            _safe_get(body, "message", "type", default="unknown"),
            list(body.keys()),
        )
        return JSONResponse(status_code=200, content={})

    # ------------------------------------------------------------------
    # 2. Extract common fields
    # ------------------------------------------------------------------
    msg_type = message.type
    call_obj = _safe_get(body, "message", "call") or {}
    vapi_call_id = _safe_get(call_obj, "id")
    caller_phone = _safe_get(call_obj, "customer", "number")

    # ------------------------------------------------------------------
    # 3. Resolve practice_id
    # ------------------------------------------------------------------
    try:
        practice_id = await _resolve_practice_id(db, vapi_call_id, call_obj)
    except Exception as e:
        logger.error("vapi_webhook: practice resolution failed: %s", e)
        practice_id = None

    if not practice_id:
        logger.error(
            "vapi_webhook: could not resolve practice for call %s, returning 200",
            vapi_call_id,
        )
        # Still return 200 -- we never want Vapi to retry
        return JSONResponse(status_code=200, content={})

    # ------------------------------------------------------------------
    # 4. Dispatch by message type
    # ------------------------------------------------------------------
    try:
        # ---- assistant-request ----
        if msg_type == "assistant-request":
            return await _handle_assistant_request(db, message, practice_id)

        # ---- status-update ----
        elif msg_type == "status-update":
            return await _handle_status_update(
                db, message, practice_id, vapi_call_id, caller_phone, call_obj,
            )

        # ---- tool-calls ----
        elif msg_type == "tool-calls":
            return await _handle_tool_calls(
                db, message, body, practice_id, vapi_call_id,
            )

        # ---- function-call (legacy) ----
        elif msg_type == "function-call":
            return await _handle_function_call(
                db, message, body, practice_id, vapi_call_id,
            )

        # ---- end-of-call-report ----
        elif msg_type == "end-of-call-report":
            return await _handle_end_of_call_report(
                db, message, body, vapi_call_id, call_obj,
            )

        # ---- hang ----
        elif msg_type == "hang":
            logger.info("vapi_webhook: hang event for call %s", vapi_call_id)
            return JSONResponse(status_code=200, content={})

        # ---- unknown / other ----
        else:
            logger.info("vapi_webhook: unhandled message type '%s'", msg_type)
            return JSONResponse(status_code=200, content={})

    except Exception as e:
        logger.exception("vapi_webhook: unhandled error processing type=%s: %s", msg_type, e)
        return JSONResponse(status_code=200, content={})


# ---------------------------------------------------------------------------
# Handler: assistant-request
# ---------------------------------------------------------------------------

async def _handle_assistant_request(
    db: AsyncSession,
    message,
    practice_id: UUID,
) -> JSONResponse:
    """
    Vapi is asking for assistant configuration.

    Returns the configured assistant ID so Vapi uses the saved assistant.
    """
    logger.info("vapi_webhook: assistant-request for practice %s", practice_id)
    # Return None to use the assistant already configured on the Vapi dashboard
    return JSONResponse(status_code=200, content={"assistant": None})


# ---------------------------------------------------------------------------
# Handler: status-update
# ---------------------------------------------------------------------------

async def _handle_status_update(
    db: AsyncSession,
    message,
    practice_id: UUID,
    vapi_call_id: str | None,
    caller_phone: str | None,
    call_obj: dict,
) -> JSONResponse:
    """
    Call status changed. Create or update the call record accordingly.

    Statuses: scheduled, queued, ringing, in-progress, forwarding, ended
    """
    status = message.status or _safe_get(call_obj, "status")
    logger.info(
        "vapi_webhook: status-update status=%s call=%s",
        status, vapi_call_id,
    )

    if not vapi_call_id:
        logger.warning("vapi_webhook: status-update with no call id")
        return JSONResponse(status_code=200, content={})

    try:
        # Determine direction from the call type (used for all statuses)
        call_type = call_obj.get("type", "")
        if "outbound" in call_type.lower():
            direction = "outbound"
        else:
            direction = "inbound"

        if status == "in-progress":
            await create_or_update_call(
                db,
                practice_id=practice_id,
                vapi_call_id=vapi_call_id,
                caller_phone=caller_phone,
                status="in-progress",
                direction=direction,
                started_at=datetime.now(timezone.utc),
            )
        elif status == "ended":
            # Try update first; if call doesn't exist yet, create it
            call = await update_call_status(
                db,
                vapi_call_id=vapi_call_id,
                status="ended",
                ended_at=datetime.now(timezone.utc),
            )
            if not call:
                await create_or_update_call(
                    db,
                    practice_id=practice_id,
                    vapi_call_id=vapi_call_id,
                    caller_phone=caller_phone,
                    status="ended",
                    direction=direction,
                    ended_at=datetime.now(timezone.utc),
                )
        else:
            # For other statuses (queued, ringing, forwarding, etc.)
            # Use create_or_update so early events also create the record
            await create_or_update_call(
                db,
                practice_id=practice_id,
                vapi_call_id=vapi_call_id,
                caller_phone=caller_phone,
                status=status or "unknown",
                direction=direction,
            )
    except Exception as e:
        logger.exception(
            "vapi_webhook: error handling status-update for call %s: %s",
            vapi_call_id, e,
        )

    return JSONResponse(status_code=200, content={})


# ---------------------------------------------------------------------------
# Handler: tool-calls
# ---------------------------------------------------------------------------

async def _handle_tool_calls(
    db: AsyncSession,
    message,
    body: dict,
    practice_id: UUID,
    vapi_call_id: str | None,
) -> JSONResponse:
    """
    Vapi is requesting tool call execution. This MUST return results.

    Vapi sends tool calls in two possible formats:
    1. toolWithToolCallList (newer): [{type, name, toolCall: {id, function: {arguments}}}]
    2. toolCallList (older): [{id, name, function: {name, arguments}}]
    """
    results: list[VapiToolCallResult] = []

    # ------------------------------------------------------------------
    # Try newer format first: toolWithToolCallList
    # ------------------------------------------------------------------
    raw_tool_with_list = _safe_get(body, "message", "toolWithToolCallList")

    if raw_tool_with_list and isinstance(raw_tool_with_list, list):
        for item in raw_tool_with_list:
            tool_call_id = None
            tool_name = None
            params = {}

            try:
                # Tool name is on the outer object
                tool_name = item.get("name")

                # The nested toolCall has the id and arguments
                tc = item.get("toolCall", {})
                tool_call_id = tc.get("id", "")

                # Arguments may be in toolCall.function.arguments (JSON string)
                # or toolCall.arguments (dict)
                raw_args = _safe_get(tc, "function", "arguments")
                if raw_args is None:
                    raw_args = tc.get("arguments", {})
                params = parse_params(raw_args)

                # Fall back name from toolCall.function.name
                if not tool_name:
                    tool_name = _safe_get(tc, "function", "name") or tc.get("name")

            except Exception as e:
                logger.error(
                    "vapi_webhook: error parsing toolWithToolCallList item: %s", e,
                )

            if tool_name and tool_call_id:
                result = await _execute_tool_call(
                    db, practice_id, tool_name, params, vapi_call_id, tool_call_id,
                )
                results.append(result)
            else:
                logger.warning(
                    "vapi_webhook: skipping tool call with missing name=%s or id=%s",
                    tool_name, tool_call_id,
                )
                if tool_call_id:
                    results.append(VapiToolCallResult(
                        toolCallId=tool_call_id,
                        result="Error: could not determine tool name",
                    ))

    # ------------------------------------------------------------------
    # Fall back to older format: toolCallList
    # ------------------------------------------------------------------
    elif message.toolCallList:
        for tc in message.toolCallList:
            tool_call_id = tc.id
            tool_name = tc.name

            # Name might be in function dict
            if not tool_name and tc.function:
                tool_name = tc.function.get("name")

            # Arguments from function.arguments
            raw_args = {}
            if tc.function:
                raw_args = tc.function.get("arguments", {})
            params = parse_params(raw_args)

            if tool_name:
                result = await _execute_tool_call(
                    db, practice_id, tool_name, params, vapi_call_id, tool_call_id,
                )
                results.append(result)
            else:
                logger.warning(
                    "vapi_webhook: toolCallList item missing name, id=%s",
                    tool_call_id,
                )
                results.append(VapiToolCallResult(
                    toolCallId=tool_call_id,
                    result="Error: could not determine tool name",
                ))

    # ------------------------------------------------------------------
    # No tool calls found at all
    # ------------------------------------------------------------------
    else:
        logger.warning("vapi_webhook: tool-calls message but no tool calls found in body")
        return JSONResponse(status_code=200, content={"results": []})

    # Build and return the response Vapi expects
    response = VapiToolCallResponse(results=results)
    return JSONResponse(
        status_code=200,
        content=response.model_dump(mode="json"),
    )


async def _execute_tool_call(
    db: AsyncSession,
    practice_id: UUID,
    tool_name: str,
    params: dict,
    vapi_call_id: str | None,
    tool_call_id: str,
) -> VapiToolCallResult:
    """
    Execute a single tool call via the vapi_tools dispatcher.
    Wraps errors so one failing tool does not crash the entire response.
    """
    try:
        # Log tool name and param keys only — values may contain PHI
        logger.info(
            "vapi_webhook: executing tool '%s' param_keys=%s (call=%s)",
            tool_name,
            list(params.keys()) if isinstance(params, dict) else "n/a",
            vapi_call_id,
        )
        result = await dispatch_tool_call(
            db=db,
            practice_id=practice_id,
            tool_name=tool_name,
            params=params,
            vapi_call_id=vapi_call_id,
        )
        return VapiToolCallResult(toolCallId=tool_call_id, result=result)
    except Exception as e:
        logger.exception(
            "vapi_webhook: tool '%s' failed: %s", tool_name, e,
        )
        # Return generic message to Vapi — don't leak internal errors to AI/caller
        return VapiToolCallResult(
            toolCallId=tool_call_id,
            result=f"Sorry, the {tool_name} function encountered an error. Please try again.",
        )


# ---------------------------------------------------------------------------
# Handler: function-call (legacy)
# ---------------------------------------------------------------------------

async def _handle_function_call(
    db: AsyncSession,
    message,
    body: dict,
    practice_id: UUID,
    vapi_call_id: str | None,
) -> JSONResponse:
    """
    Legacy single function call format.

    Message contains: functionCall: {name: "...", parameters: {...}}
    Must return: {"result": ...}
    """
    func_call = _safe_get(body, "message", "functionCall") or {}
    func_name = func_call.get("name")
    raw_params = func_call.get("parameters", {})
    params = parse_params(raw_params)

    if not func_name:
        logger.warning("vapi_webhook: function-call with no function name")
        return JSONResponse(
            status_code=200,
            content={"result": "Error: no function name provided"},
        )

    try:
        logger.info(
            "vapi_webhook: executing function '%s' with %d params (call=%s)",
            func_name,
            len(params) if isinstance(params, dict) else 0,
            vapi_call_id,
        )
        result = await dispatch_tool_call(
            db=db,
            practice_id=practice_id,
            tool_name=func_name,
            params=params,
            vapi_call_id=vapi_call_id,
        )
        return JSONResponse(status_code=200, content={"result": result})
    except Exception as e:
        logger.exception(
            "vapi_webhook: function '%s' failed: %s", func_name, e,
        )
        # Return generic message — don't leak internal errors to AI/caller
        return JSONResponse(
            status_code=200,
            content={"result": f"Sorry, the {func_name} function encountered an error. Please try again."},
        )


# ---------------------------------------------------------------------------
# Handler: end-of-call-report
# ---------------------------------------------------------------------------

async def _handle_end_of_call_report(
    db: AsyncSession,
    message,
    body: dict,
    vapi_call_id: str | None,
    call_obj: dict,
) -> JSONResponse:
    """
    Call has ended. Persist transcript, recording, summary, cost, duration.
    """
    if not vapi_call_id:
        logger.warning("vapi_webhook: end-of-call-report with no call id")
        return JSONResponse(status_code=200, content={})

    try:
        # Extract transcript -- prefer the plain text transcript, fall back to messages
        artifact = _safe_get(body, "message", "artifact") or {}
        transcript = artifact.get("transcript")
        if not transcript and artifact.get("messages"):
            # Build transcript from message list
            parts = []
            for msg in artifact["messages"]:
                role = msg.get("role", "unknown")
                content = msg.get("content") or msg.get("message", "")
                if content:
                    parts.append(f"{role}: {content}")
            transcript = "\n".join(parts) if parts else None

        # Extract recording URL
        recording_url = (
            artifact.get("recordingUrl")
            or _safe_get(artifact, "recording", "url")
        )

        # Extract summary and structured data from analysis
        analysis = _safe_get(body, "message", "analysis") or {}
        summary = analysis.get("summary")
        structured_data = analysis.get("structuredData")
        success_evaluation = analysis.get("successEvaluation")

        logger.info(
            "vapi_webhook: analysis data for call %s: summary=%s, structured=%s, success=%s",
            vapi_call_id,
            bool(summary),
            bool(structured_data),
            success_evaluation,
        )

        # Ended reason
        ended_reason = (
            _safe_get(body, "message", "endedReason")
            or call_obj.get("endedReason")
        )

        # Cost
        cost = call_obj.get("cost")
        if cost is not None:
            try:
                cost = float(cost)
            except (ValueError, TypeError):
                cost = None

        # Duration (seconds)
        duration = call_obj.get("duration")
        if duration is None:
            # Try to calculate from timestamps
            started = call_obj.get("startedAt")
            ended = call_obj.get("endedAt")
            if started and ended:
                try:
                    started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                    ended_dt = datetime.fromisoformat(ended.replace("Z", "+00:00"))
                    duration = int((ended_dt - started_dt).total_seconds())
                except (ValueError, TypeError):
                    pass
        else:
            try:
                duration = int(duration)
            except (ValueError, TypeError):
                duration = None

        logger.info(
            "vapi_webhook: end-of-call-report call=%s reason=%s cost=%s duration=%s",
            vapi_call_id, ended_reason, cost, duration,
        )

        await save_end_of_call_report(
            db=db,
            vapi_call_id=vapi_call_id,
            transcript=transcript,
            recording_url=recording_url,
            summary=summary,
            duration=duration,
            cost=cost,
            ended_reason=ended_reason,
        )

        # Single query to get the call record (reused for structured data,
        # callback flagging, and feedback loop — avoids 3 redundant SELECTs)
        stmt = select(Call).where(Call.vapi_call_id == vapi_call_id)
        result = await db.execute(stmt)
        call_record = result.scalar_one_or_none()

        # Save structured analysis data if available
        if call_record and (structured_data or success_evaluation):
            try:
                if structured_data and isinstance(structured_data, dict):
                    call_record.structured_data = structured_data
                    # Extract key fields for quick filtering
                    if structured_data.get("caller_intent"):
                        call_record.caller_intent = structured_data["caller_intent"]
                    if structured_data.get("caller_sentiment"):
                        call_record.caller_sentiment = structured_data["caller_sentiment"]
                    if structured_data.get("language"):
                        lang_map = {"english": "en", "spanish": "es"}
                        call_record.language = lang_map.get(
                            structured_data["language"], structured_data["language"][:5]
                        )
                if success_evaluation is not None:
                    call_record.success_evaluation = str(success_evaluation)
                await db.flush()
                logger.info(
                    "vapi_webhook: saved structured analysis for call %s (intent=%s, sentiment=%s)",
                    vapi_call_id,
                    structured_data.get("caller_intent") if structured_data else None,
                    structured_data.get("caller_sentiment") if structured_data else None,
                )
            except Exception as e:
                logger.warning("vapi_webhook: failed to save structured data: %s", e)

        # Auto-flag for callback if call was dropped/missed and we have caller info
        CALLBACK_REASONS = {
            'customer-did-not-answer', 'customer-busy',
            'assistant-error', 'phone-call-provider-closed-websocket',
            'assistant-forwarded-call', 'voicemail',
        }
        if ended_reason in CALLBACK_REASONS or (duration is not None and duration < 15):
            try:
                if call_record and (call_record.caller_name or call_record.caller_phone):
                    call_record.callback_needed = True
                    await db.flush()
                    logger.info("vapi_webhook: flagged call %s for callback (reason=%s)", vapi_call_id, ended_reason)
            except Exception as e:
                logger.warning("vapi_webhook: failed to flag callback: %s", e)

        # Trigger self-improving feedback loop (non-blocking)
        try:
            if call_record:
                import asyncio
                # Run feedback analysis in background (don't block webhook response)
                asyncio.create_task(
                    _run_feedback_analysis(call_record.id, call_record.practice_id)
                )
        except Exception as e:
            logger.warning("vapi_webhook: failed to trigger feedback loop: %s", e)

    except Exception as e:
        logger.exception(
            "vapi_webhook: error saving end-of-call-report for call %s: %s",
            vapi_call_id, e,
        )

    return JSONResponse(status_code=200, content={})


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@router.get("/vapi/health")
async def vapi_webhook_health():
    """Simple health/test endpoint to verify the webhook route is active."""
    return {"status": "ok", "message": "Vapi webhook endpoint is active"}


# ---------------------------------------------------------------------------
# Call listing endpoint (authenticated, practice-scoped)
# ---------------------------------------------------------------------------

def _ensure_practice(user: User, practice_id_override: UUID | None = None) -> UUID:
    """Return the effective practice_id for the current request.

    - Regular staff: always use their own practice_id (override ignored).
    - Super admin: use ``practice_id_override`` if provided, otherwise
      fall back to their own practice_id (which may be None).
    - Raises 400 if no practice can be resolved at all.
    """
    if user.role == "super_admin" and practice_id_override:
        return practice_id_override
    if user.practice_id:
        return user.practice_id
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No practice associated with this user. Super admins must pass ?practice_id=<uuid>.",
    )


@router.get("/calls", response_model=CallListResponse)
async def list_calls(
    from_date: date | None = Query(None, description="Filter calls from this date"),
    to_date: date | None = Query(None, description="Filter calls to this date"),
    direction: str | None = Query(None, description="Filter by direction: inbound or outbound"),
    status_filter: str | None = Query(None, alias="status", description="Filter by status: ringing, in-progress, ended"),
    search: str | None = Query(None, description="Search by caller phone number (partial match)"),
    practice_id: UUID | None = Query(None, description="Practice ID (super_admin only)"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """
    List calls for the current practice with optional filters.

    Returns paginated call records with joined patient names.
    """
    practice_id = _ensure_practice(current_user, practice_id)

    # Base filters — always scoped to the user's practice
    filters = [Call.practice_id == practice_id]

    # Date range filters (compare against started_at, falling back to created_at)
    if from_date:
        from_dt = datetime.combine(from_date, datetime.min.time(), tzinfo=timezone.utc)
        filters.append(
            func.coalesce(Call.started_at, Call.created_at) >= from_dt
        )
    if to_date:
        # Include the entire to_date day
        to_dt = datetime.combine(to_date, datetime.max.time(), tzinfo=timezone.utc)
        filters.append(
            func.coalesce(Call.started_at, Call.created_at) <= to_dt
        )

    # Cap date range to 365 days to prevent expensive full-table scans
    if from_date and to_date and (to_date - from_date).days > 365:
        raise HTTPException(status_code=400, detail="Date range cannot exceed 365 days.")

    # Direction filter
    VALID_DIRECTIONS = {"inbound", "outbound"}
    if direction:
        if direction not in VALID_DIRECTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid direction. Must be one of: {', '.join(sorted(VALID_DIRECTIONS))}",
            )
        filters.append(Call.direction == direction)

    # Status filter
    VALID_CALL_STATUSES = {"ringing", "queued", "in-progress", "forwarding", "ended"}
    if status_filter:
        if status_filter not in VALID_CALL_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_CALL_STATUSES))}",
            )
        filters.append(Call.status == status_filter)

    # Phone search (partial match on caller_phone) — escape ILIKE wildcards
    if search:
        safe_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(Call.caller_phone.ilike(f"%{safe_search}%"))

    # ------------------------------------------------------------------
    # Total count
    # ------------------------------------------------------------------
    count_query = select(func.count(Call.id)).where(*filters)
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # ------------------------------------------------------------------
    # Paginated query with optional Patient join for patient_name
    # ------------------------------------------------------------------
    PatientAlias = aliased(Patient)

    query = (
        select(
            Call,
            func.concat(PatientAlias.first_name, " ", PatientAlias.last_name).label(
                "patient_name"
            ),
        )
        .outerjoin(PatientAlias, Call.patient_id == PatientAlias.id)
        .where(*filters)
        .order_by(func.coalesce(Call.started_at, Call.created_at).desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    rows = result.all()

    # ------------------------------------------------------------------
    # Build response, mapping model field names to API field names
    # ------------------------------------------------------------------
    calls: list[CallResponse] = []
    for row in rows:
        call: Call = row[0]
        patient_name: str | None = row[1] if call.patient_id else None

        calls.append(
            CallResponse(
                id=call.id,
                vapi_call_id=call.vapi_call_id,
                direction=call.direction,
                caller_number=call.caller_phone,
                caller_name=call.caller_name,
                status=call.status,
                duration_seconds=call.duration_seconds,
                patient_id=call.patient_id,
                patient_name=patient_name,
                started_at=call.started_at,
                ended_at=call.ended_at,
                transcript=call.transcription,
                summary=call.ai_summary,
                cost=call.vapi_cost,
                recording_url=call.recording_url,
                created_at=call.created_at,
                ended_reason=call.outcome,
                callback_needed=call.callback_needed if hasattr(call, 'callback_needed') else False,
                callback_completed=call.callback_completed if hasattr(call, 'callback_completed') else False,
                callback_notes=call.callback_notes if hasattr(call, 'callback_notes') else None,
                callback_completed_at=call.callback_completed_at if hasattr(call, 'callback_completed_at') else None,
                structured_data=call.structured_data if hasattr(call, 'structured_data') else None,
                caller_intent=call.caller_intent if hasattr(call, 'caller_intent') else None,
                caller_sentiment=call.caller_sentiment if hasattr(call, 'caller_sentiment') else None,
                success_evaluation=call.success_evaluation if hasattr(call, 'success_evaluation') else None,
                language=call.language,
            )
        )

    return CallListResponse(calls=calls, total=total)


# ---------------------------------------------------------------------------
# Callback management endpoints
# ---------------------------------------------------------------------------

@router.get("/callbacks", response_model=CallbackListResponse)
async def list_callbacks(
    include_completed: bool = Query(False, description="Include already completed callbacks"),
    practice_id: UUID | None = Query(None, description="Practice ID (super_admin only)"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """List calls that need callbacks (missed/dropped calls with caller info)."""
    practice_id = _ensure_practice(current_user, practice_id)

    filters = [
        Call.practice_id == practice_id,
        Call.callback_needed == True,
    ]
    if not include_completed:
        filters.append(Call.callback_completed == False)

    # Count
    count_query = select(func.count(Call.id)).where(*filters)
    total = (await db.execute(count_query)).scalar_one()

    # Query with patient join
    PatientAlias = aliased(Patient)
    query = (
        select(Call, func.concat(PatientAlias.first_name, " ", PatientAlias.last_name).label("patient_name"))
        .outerjoin(PatientAlias, Call.patient_id == PatientAlias.id)
        .where(*filters)
        .order_by(func.coalesce(Call.started_at, Call.created_at).desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(query)).all()

    callbacks = []
    for row in rows:
        call = row[0]
        patient_name = row[1] if call.patient_id else None
        callbacks.append(CallResponse(
            id=call.id,
            vapi_call_id=call.vapi_call_id,
            direction=call.direction,
            caller_number=call.caller_phone,
            caller_name=call.caller_name,
            status=call.status,
            duration_seconds=call.duration_seconds,
            patient_id=call.patient_id,
            patient_name=patient_name,
            started_at=call.started_at,
            ended_at=call.ended_at,
            transcript=call.transcription,
            summary=call.ai_summary,
            cost=call.vapi_cost,
            recording_url=call.recording_url,
            created_at=call.created_at,
            ended_reason=call.outcome,
            callback_needed=call.callback_needed,
            callback_completed=call.callback_completed,
            callback_notes=call.callback_notes,
            callback_completed_at=call.callback_completed_at,
        ))

    return CallbackListResponse(callbacks=callbacks, total=total)


@router.patch("/calls/{call_id}/callback")
async def update_callback(
    call_id: UUID,
    request: CallbackUpdateRequest,
    practice_id: UUID | None = Query(None, description="Practice ID (super_admin only)"),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Mark a callback as completed or add notes."""
    practice_id = _ensure_practice(current_user, practice_id)

    result = await db.execute(
        select(Call).where(Call.id == call_id, Call.practice_id == practice_id)
    )
    call = result.scalar_one_or_none()

    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    if request.callback_completed is not None:
        call.callback_completed = request.callback_completed
        if request.callback_completed:
            call.callback_completed_at = datetime.now(timezone.utc)
            call.callback_completed_by = current_user.id
        else:
            call.callback_completed_at = None
            call.callback_completed_by = None

    if request.callback_notes is not None:
        call.callback_notes = request.callback_notes

    await db.commit()
    await db.refresh(call)

    return {"status": "ok", "callback_completed": call.callback_completed}


@router.get("/calls/stats", response_model=CallStatsResponse)
async def get_call_stats(
    practice_id: UUID | None = Query(None, description="Practice ID (super_admin only)"),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Get call statistics for the dashboard."""
    practice_id = _ensure_practice(current_user, practice_id)

    from datetime import timedelta

    today_start = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)
    today_end = datetime.combine(date.today(), datetime.max.time(), tzinfo=timezone.utc)
    week_start = datetime.combine(date.today() - timedelta(days=7), datetime.min.time(), tzinfo=timezone.utc)

    base = [Call.practice_id == practice_id]
    today_filter = base + [func.coalesce(Call.started_at, Call.created_at) >= today_start, func.coalesce(Call.started_at, Call.created_at) <= today_end]
    week_filter = base + [func.coalesce(Call.started_at, Call.created_at) >= week_start]

    # Total calls today
    total_today = (await db.execute(select(func.count(Call.id)).where(*today_filter))).scalar_one()

    # Missed calls today (ended_reason indicates customer/assistant hung up prematurely)
    missed_reasons = ['customer-did-not-answer', 'customer-busy', 'customer-ended-call', 'assistant-error', 'phone-call-provider-closed-websocket']
    missed_today = (await db.execute(
        select(func.count(Call.id)).where(*today_filter, Call.outcome.in_(missed_reasons))
    )).scalar_one()

    # Average duration today
    avg_dur = (await db.execute(
        select(func.avg(Call.duration_seconds)).where(*today_filter, Call.duration_seconds.isnot(None))
    )).scalar_one()

    # Pending callbacks
    callbacks_pending = (await db.execute(
        select(func.count(Call.id)).where(*base, Call.callback_needed == True, Call.callback_completed == False)
    )).scalar_one()

    # Total calls this week
    total_week = (await db.execute(select(func.count(Call.id)).where(*week_filter))).scalar_one()

    # Total cost today
    total_cost = (await db.execute(
        select(func.sum(Call.vapi_cost)).where(*today_filter)
    )).scalar_one()

    return CallStatsResponse(
        total_calls_today=total_today,
        missed_calls_today=missed_today,
        avg_duration_seconds=int(avg_dur or 0),
        callbacks_pending=callbacks_pending,
        total_calls_week=total_week,
        total_cost_today=float(total_cost or 0),
    )
