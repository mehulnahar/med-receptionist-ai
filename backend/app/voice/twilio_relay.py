"""
Twilio ConversationRelay WebSocket endpoint.

Handles bidirectional audio streaming between Twilio and our voice pipeline.
"""

import asyncio
import base64
import json
import logging
import time
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.voice.conversation_manager import get_conversation_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws")
async def twilio_conversation_relay(
    websocket: WebSocket,
    practice_id: str = Query(default=""),
):
    """Twilio ConversationRelay WebSocket endpoint.

    Twilio sends audio via WebSocket messages.
    We transcribe, process with Claude, synthesize speech, and send back.

    WebSocket message types from Twilio:
      - connected: initial connection info
      - start: stream start with metadata
      - media: audio chunk (base64 encoded mulaw)
      - stop: stream ended
    """
    await websocket.accept()
    call_id = str(uuid4())
    manager = get_conversation_manager()
    audio_buffer = bytearray()
    stream_sid: Optional[str] = None
    call_started = False

    logger.info("WebSocket connected: call_id=%s practice_id=%s", call_id, practice_id)

    try:
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            event_type = data.get("event")

            if event_type == "connected":
                logger.info("Twilio stream connected: %s", data.get("protocol"))

            elif event_type == "start":
                stream_sid = data.get("start", {}).get("streamSid")
                call_sid = data.get("start", {}).get("callSid", "")
                custom_params = data.get("start", {}).get("customParameters", {})

                # Get practice info from custom parameters or defaults
                clinic_name = custom_params.get("clinic_name", "Medical Office")
                doctor_name = custom_params.get("doctor_name", "")
                language = custom_params.get("language", "en")

                await manager.start_call(
                    call_id=call_id,
                    practice_id=practice_id or custom_params.get("practice_id", ""),
                    clinic_name=clinic_name,
                    doctor_name=doctor_name,
                    language=language,
                )
                call_started = True

                # Send initial greeting
                greeting_text = _get_greeting(clinic_name, language)
                await _send_text_response(websocket, stream_sid, greeting_text)

                logger.info(
                    "Call started: call_id=%s stream=%s clinic=%s lang=%s",
                    call_id, stream_sid, clinic_name, language,
                )

            elif event_type == "media":
                # Accumulate audio chunks
                payload = data.get("media", {}).get("payload", "")
                if payload:
                    audio_bytes = base64.b64decode(payload)
                    audio_buffer.extend(audio_bytes)

                    # Process when we have enough audio (~2 seconds of 8kHz mulaw)
                    if len(audio_buffer) >= 16000:
                        chunk = bytes(audio_buffer)
                        audio_buffer.clear()

                        # Process through pipeline — use a proper async
                        # callback, not a lambda (lambda returns a coroutine
                        # but is not itself awaitable in the expected way)
                        async def _audio_callback(audio: bytes, _ws=websocket, _sid=stream_sid):
                            await _send_audio(_ws, _sid, audio)

                        response = await manager.process_audio(
                            call_id=call_id,
                            audio_data=chunk,
                            on_audio_response=_audio_callback,
                        )

            elif event_type == "stop":
                logger.info("Twilio stream stopped: call_id=%s", call_id)
                break

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: call_id=%s", call_id)
    except Exception as e:
        logger.error("WebSocket error: call_id=%s error=%s", call_id, e)
    finally:
        if call_started:
            summary = await manager.end_call(call_id)
            if summary:
                logger.info(
                    "Call summary: %s turns=%d duration=%.0fs",
                    call_id, summary["turn_count"], summary["duration_seconds"],
                )
        try:
            await websocket.close()
        except Exception:
            pass


async def _send_text_response(
    websocket: WebSocket,
    stream_sid: Optional[str],
    text: str,
) -> None:
    """Send a text response back to Twilio (for ConversationRelay)."""
    if not text:
        return
    try:
        await websocket.send_json({
            "event": "media",
            "streamSid": stream_sid,
            "media": {
                "text": text,
            },
        })
    except Exception as e:
        logger.error("Failed to send text response: %s", e)


async def _send_audio(
    websocket: WebSocket,
    stream_sid: Optional[str],
    audio_data: bytes,
) -> None:
    """Send audio data back to Twilio."""
    if not audio_data:
        return
    try:
        payload = base64.b64encode(audio_data).decode("ascii")
        await websocket.send_json({
            "event": "media",
            "streamSid": stream_sid,
            "media": {
                "payload": payload,
            },
        })
    except Exception as e:
        logger.error("Failed to send audio: %s", e)


def _get_greeting(clinic_name: str, language: str) -> str:
    """Get the initial greeting for a call."""
    if language == "es":
        return (
            f"Gracias por llamar a {clinic_name}. "
            "Soy la recepcionista de inteligencia artificial. "
            "Como puedo ayudarle hoy?"
        )
    return (
        f"Thank you for calling {clinic_name}. "
        "I'm the AI receptionist. "
        "How can I help you today?"
    )
