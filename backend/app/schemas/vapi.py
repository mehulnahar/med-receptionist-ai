"""
Pydantic schemas for Vapi.ai webhook payloads.

Vapi sends all webhooks as POST requests with body: {"message": {"type": "...", ...}}
The "type" field determines the message type. These schemas provide typed access
to the webhook data while allowing extra fields via model_config for forward
compatibility as Vapi evolves its API.

Key message types:
- assistant-request: Vapi asks for assistant configuration
- tool-calls: Vapi triggers tool functions (respond with results)
- status-update: Call status changed (scheduled|queued|ringing|in-progress|forwarding|ended)
- end-of-call-report: Call ended, includes transcript/recording/summary
- hang: Call hang notification
- function-call: Legacy function call format
"""

from pydantic import BaseModel
from typing import Any


# ---------------------------------------------------------------------------
# Vapi call object (present in every webhook)
# ---------------------------------------------------------------------------

class VapiCallObject(BaseModel):
    """The call object included in every Vapi webhook."""
    id: str | None = None  # Vapi call ID
    orgId: str | None = None
    type: str | None = None  # inboundPhoneCall, outboundPhoneCall, webCall
    status: str | None = None
    phoneNumberId: str | None = None
    assistantId: str | None = None
    customer: dict[str, Any] | None = None  # {number: "+1...", name: "..."}
    createdAt: str | None = None
    startedAt: str | None = None
    endedAt: str | None = None
    endedReason: str | None = None
    cost: float | None = None

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Tool call schemas
# ---------------------------------------------------------------------------

class VapiToolCall(BaseModel):
    """A single tool call from Vapi."""
    id: str  # Tool call ID - must be returned in response
    name: str | None = None  # Function name (may also be in parent)
    type: str | None = None
    function: dict[str, Any] | None = None  # {name: "...", arguments: "..."}

    model_config = {"extra": "allow"}


class VapiToolWithToolCall(BaseModel):
    """Tool definition paired with its call."""
    type: str | None = None
    name: str | None = None  # Function name
    toolCall: VapiToolCall | None = None
    function: dict[str, Any] | None = None

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# End-of-call artifact
# ---------------------------------------------------------------------------

class VapiArtifact(BaseModel):
    """Artifact from end-of-call report."""
    messages: list[dict[str, Any]] | None = None
    transcript: str | None = None
    recordingUrl: str | None = None
    recording: dict[str, Any] | None = None

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Main message envelope
# ---------------------------------------------------------------------------

class VapiMessage(BaseModel):
    """
    The outer message envelope from Vapi webhooks.

    The 'type' field determines which other fields are populated:
    - assistant-request: call
    - tool-calls: call, toolCallList, toolWithToolCallList
    - function-call: call, functionCall (legacy)
    - status-update: call, status
    - end-of-call-report: call, endedReason, artifact, analysis
    - hang: call
    - transcript: call, transcript, transcriptType
    """
    type: str  # assistant-request, tool-calls, function-call, status-update, end-of-call-report, hang, etc.
    call: VapiCallObject | None = None

    # For tool-calls type
    toolCallList: list[VapiToolCall] | None = None
    toolWithToolCallList: list[VapiToolWithToolCall] | None = None

    # For function-call type (legacy)
    functionCall: dict[str, Any] | None = None

    # For status-update type
    status: str | None = None

    # For end-of-call-report type
    endedReason: str | None = None
    artifact: VapiArtifact | None = None

    # For transcript type
    transcript: str | None = None
    transcriptType: str | None = None

    # Analysis/summary (end-of-call-report)
    analysis: dict[str, Any] | None = None

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Top-level webhook request
# ---------------------------------------------------------------------------

class VapiWebhookRequest(BaseModel):
    """Top-level Vapi webhook request body: {"message": {...}}"""
    message: VapiMessage

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Response schemas (sent back to Vapi)
# ---------------------------------------------------------------------------

class VapiToolCallResult(BaseModel):
    """A single tool call result to return to Vapi."""
    toolCallId: str
    result: Any  # Can be string, dict, list, etc.


class VapiToolCallResponse(BaseModel):
    """Response to Vapi tool-calls webhook."""
    results: list[VapiToolCallResult]
