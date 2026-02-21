"""
Conversation Manager — orchestrates the full voice call pipeline.

Pipeline: Twilio Audio → Whisper STT → Triage → Router → Claude LLM → Chatterbox TTS → Twilio Audio
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable
from uuid import uuid4

from app.voice.stt import get_stt_client
from app.voice.tts import get_tts_client
from app.voice.llm_engine import get_llm_engine, build_system_prompt
from app.voice.triage import detect_urgency, UrgencyLevel
from app.voice.router import classify_query, ModelTier

logger = logging.getLogger(__name__)


@dataclass
class CallSession:
    """Represents an active phone call."""
    call_id: str
    practice_id: str
    clinic_name: str = ""
    doctor_name: str = ""
    address: str = ""
    phone: str = ""
    hours: str = ""
    language: str = "en"
    started_at: float = field(default_factory=time.time)
    turn_count: int = 0
    total_stt_ms: float = 0
    total_llm_ms: float = 0
    total_tts_ms: float = 0
    is_active: bool = True
    transfer_requested: bool = False
    transfer_reason: str = ""


class ConversationManager:
    """Manages active call sessions and orchestrates the voice pipeline."""

    def __init__(self):
        self._sessions: dict[str, CallSession] = {}
        self._stt = get_stt_client()
        self._tts = get_tts_client()
        self._llm = get_llm_engine()

    async def start_call(
        self,
        call_id: str,
        practice_id: str,
        clinic_name: str,
        doctor_name: str = "",
        address: str = "",
        phone: str = "",
        hours: str = "",
        language: str = "en",
        custom_instructions: str = "",
    ) -> CallSession:
        """Initialize a new call session with all required context."""
        session = CallSession(
            call_id=call_id,
            practice_id=practice_id,
            clinic_name=clinic_name,
            doctor_name=doctor_name,
            address=address,
            phone=phone,
            hours=hours,
            language=language,
        )
        self._sessions[call_id] = session

        # Build system prompt and create LLM session
        system_prompt = build_system_prompt(
            clinic_name=clinic_name,
            doctor_name=doctor_name,
            address=address,
            phone=phone,
            hours=hours,
            language=language,
            custom_instructions=custom_instructions,
        )
        self._llm.create_session(
            call_id=call_id,
            practice_id=practice_id,
            system_prompt=system_prompt,
            language=language,
        )

        logger.info(
            "Call started: %s (practice=%s, language=%s)",
            call_id, practice_id, language,
        )
        return session

    async def process_audio(
        self,
        call_id: str,
        audio_data: bytes,
        on_audio_response: Optional[Callable[[bytes], Awaitable[None]]] = None,
    ) -> Optional[str]:
        """Process incoming audio through the full pipeline.

        1. STT: Convert audio to text
        2. Triage: Check for emergencies
        3. Route: Classify query complexity
        4. LLM: Generate response
        5. TTS: Convert response to audio

        Returns the assistant's text response.
        """
        session = self._sessions.get(call_id)
        if not session or not session.is_active:
            return None

        pipeline_start = time.monotonic()

        # 1. Speech to Text
        stt_start = time.monotonic()
        transcript = await self._stt.transcribe_chunk(
            audio_data,
            language=session.language,
        )
        stt_ms = (time.monotonic() - stt_start) * 1000
        session.total_stt_ms += stt_ms

        if not transcript or not transcript.strip():
            return None

        logger.info(
            "Call %s turn %d: STT=%.0fms text='%s'",
            call_id, session.turn_count, stt_ms, transcript[:100],
        )

        # 2. Triage — check for emergencies BEFORE LLM
        triage_result = detect_urgency(transcript, session.language)
        if triage_result.level == UrgencyLevel.EMERGENCY:
            logger.warning(
                "EMERGENCY detected in call %s: %s (%.1fms)",
                call_id, triage_result.matched_keyword, triage_result.detection_time_ms,
            )
            session.transfer_requested = True
            session.transfer_reason = f"emergency:{triage_result.matched_keyword}"

            # Send emergency message immediately via TTS
            if on_audio_response:
                audio = await self._tts.synthesize(
                    triage_result.message_to_caller, session.language
                )
                if audio:
                    await on_audio_response(audio)

            return triage_result.message_to_caller

        # 3. Route query to appropriate model
        model_tier = classify_query(transcript, session.language)
        model = "haiku" if model_tier == ModelTier.HAIKU else "sonnet"

        # 4. LLM response
        llm_start = time.monotonic()

        # For long operations, send filler phrase first
        response_text = await self._llm.generate_response(
            call_id=call_id,
            user_message=transcript,
            model=model,
        )
        llm_ms = (time.monotonic() - llm_start) * 1000
        session.total_llm_ms += llm_ms

        logger.info(
            "Call %s turn %d: LLM(%s)=%.0fms response='%s'",
            call_id, session.turn_count, model, llm_ms, response_text[:100],
        )

        # 5. Text to Speech
        tts_ms = 0.0
        if on_audio_response and response_text:
            tts_start = time.monotonic()
            audio = await self._tts.synthesize(response_text, session.language)
            tts_ms = (time.monotonic() - tts_start) * 1000
            session.total_tts_ms += tts_ms

            if audio:
                await on_audio_response(audio)

            logger.debug("Call %s turn %d: TTS=%.0fms", call_id, session.turn_count, tts_ms)

        session.turn_count += 1

        total_ms = (time.monotonic() - pipeline_start) * 1000
        logger.info(
            "Call %s turn %d: TOTAL=%.0fms (STT=%.0f LLM=%.0f TTS=%.0f)",
            call_id, session.turn_count, total_ms, stt_ms, llm_ms, tts_ms,
        )

        return response_text

    async def end_call(self, call_id: str) -> Optional[dict]:
        """End a call session and return summary metrics."""
        session = self._sessions.pop(call_id, None)
        if not session:
            return None

        session.is_active = False
        self._llm.end_session(call_id)

        duration = time.time() - session.started_at
        summary = {
            "call_id": call_id,
            "practice_id": session.practice_id,
            "duration_seconds": duration,
            "turn_count": session.turn_count,
            "language": session.language,
            "avg_stt_ms": session.total_stt_ms / max(session.turn_count, 1),
            "avg_llm_ms": session.total_llm_ms / max(session.turn_count, 1),
            "avg_tts_ms": session.total_tts_ms / max(session.turn_count, 1),
            "transfer_requested": session.transfer_requested,
            "transfer_reason": session.transfer_reason,
        }

        logger.info(
            "Call ended: %s (duration=%.0fs, turns=%d, avg_latency=%.0fms)",
            call_id, duration, session.turn_count,
            (session.total_stt_ms + session.total_llm_ms + session.total_tts_ms) / max(session.turn_count, 1),
        )

        return summary

    @property
    def active_call_count(self) -> int:
        return len(self._sessions)


_conversation_manager: Optional[ConversationManager] = None


def get_conversation_manager() -> ConversationManager:
    global _conversation_manager
    if _conversation_manager is None:
        _conversation_manager = ConversationManager()
    return _conversation_manager
