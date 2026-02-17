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

Design decisions:
- No JWT auth (Vapi calls this directly; secret verification can be added later)
- Always returns 200 (even on errors) to prevent Vapi retries that cause bad UX
- Logs everything for debugging
- Multi-tenant: resolves practice from the call's phone number
"""

import json
import logging
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Request, Depends, Query, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.database import get_db
from app.models.call import Call
from app.models.patient import Patient
from app.models.user import User
from app.middleware.auth import require_any_staff
from app.schemas.call import CallResponse, CallListResponse
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

    # 3. Fallback: first active practice (single-tenant phase)
    from app.models.practice import Practice
    from sqlalchemy import select

    stmt = (
        select(Practice.id)
        .where(Practice.status == "active")
        .order_by(Practice.created_at)
        .limit(1)
    )
    result = await db.execute(stmt)
    practice_id = result.scalar_one_or_none()

    if not practice_id:
        # Last resort: any practice at all
        stmt = select(Practice.id).order_by(Practice.created_at).limit(1)
        result = await db.execute(stmt)
        practice_id = result.scalar_one_or_none()

    if practice_id:
        logger.info("_resolve_practice_id: fallback to practice %s", practice_id)
    else:
        logger.error("_resolve_practice_id: no practice found in database")

    return practice_id


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

    This endpoint is unauthenticated -- Vapi calls it directly.
    Always returns 200 to prevent Vapi retries.
    """
    # ------------------------------------------------------------------
    # 1. Parse raw body (for logging) then as typed schema
    # ------------------------------------------------------------------
    try:
        body = await request.json()
    except Exception:
        raw = await request.body()
        logger.error("vapi_webhook: failed to parse JSON body: %s", raw[:500])
        return JSONResponse(status_code=200, content={})

    logger.info(
        "vapi_webhook: received type=%s",
        _safe_get(body, "message", "type", default="unknown"),
    )
    logger.debug("vapi_webhook: full body: %s", json.dumps(body, default=str)[:2000])

    try:
        # Parse into typed model (allows extra fields for forward compat)
        webhook = VapiWebhookRequest.model_validate(body)
        message = webhook.message
    except Exception as e:
        logger.error("vapi_webhook: schema validation failed: %s", e)
        logger.debug("vapi_webhook: body was: %s", json.dumps(body, default=str)[:2000])
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

    Return None to use the assistant already configured on the Vapi dashboard.
    In the future this can return dynamic assistant overrides per-practice.
    """
    logger.info("vapi_webhook: assistant-request for practice %s", practice_id)
    # Returning {"assistant": None} tells Vapi to use its configured assistant
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
        logger.info(
            "vapi_webhook: executing tool '%s' with params %s (call=%s)",
            tool_name,
            json.dumps(params, default=str)[:500],
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
        return VapiToolCallResult(
            toolCallId=tool_call_id,
            result=f"Error executing {tool_name}: {str(e)}",
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
            "vapi_webhook: executing function '%s' with params %s (call=%s)",
            func_name,
            json.dumps(params, default=str)[:500],
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
        return JSONResponse(
            status_code=200,
            content={"result": f"Error executing {func_name}: {str(e)}"},
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

        # Extract summary from analysis
        analysis = _safe_get(body, "message", "analysis") or {}
        summary = analysis.get("summary")

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

def _ensure_practice(user: User) -> UUID:
    """Return the user's practice_id or raise 400 if it is None."""
    if not user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )
    return user.practice_id


@router.get("/calls", response_model=CallListResponse)
async def list_calls(
    from_date: date | None = Query(None, description="Filter calls from this date"),
    to_date: date | None = Query(None, description="Filter calls to this date"),
    direction: str | None = Query(None, description="Filter by direction: inbound or outbound"),
    status_filter: str | None = Query(None, alias="status", description="Filter by status: ringing, in-progress, ended"),
    search: str | None = Query(None, description="Search by caller phone number (partial match)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """
    List calls for the current practice with optional filters.

    Returns paginated call records with joined patient names.
    """
    practice_id = _ensure_practice(current_user)

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

    # Direction filter
    if direction:
        filters.append(Call.direction == direction)

    # Status filter
    if status_filter:
        filters.append(Call.status == status_filter)

    # Phone search (partial match on caller_phone)
    if search:
        filters.append(Call.caller_phone.ilike(f"%{search}%"))

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
            )
        )

    return CallListResponse(calls=calls, total=total)
