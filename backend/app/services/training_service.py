"""
Call Recording Training Pipeline Service.

Processes uploaded call recordings to learn from real receptionist interactions:
1. Transcribes audio files using OpenAI Whisper API
2. Analyzes transcripts using GPT-4o-mini to extract call patterns
3. Aggregates insights across multiple recordings in a session
4. Generates an optimized system prompt calibrated to the practice

Flow:
  Upload audio files -> transcribe_and_store() -> analyze_recording()
  -> process_session() -> aggregate_session_insights() -> generate_training_prompt()
  -> apply_training_prompt() (pushes to Vapi)
"""

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.utils.http_client import get_http_client
from app.models.training import TrainingSession, TrainingRecording
from app.models.practice_config import PracticeConfig
from app.services.feedback_service import (
    _call_llm,
    apply_prompt_improvement,
    push_prompt_to_vapi,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WHISPER_TIMEOUT = httpx.Timeout(120.0, connect=15.0, pool=10.0)
_WHISPER_MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

TRANSCRIPT_ANALYSIS_SYSTEM_PROMPT = """You are an expert analyst for a medical office receptionist training system.
Analyze this call transcript and extract structured information about the interaction.

The transcript is from a real phone call to a medical office. The receptionist may be speaking
English, Spanish, or both. Extract patterns that will help train an AI receptionist.

Return JSON with these fields:
{
  "caller_intent": "booking" | "cancellation" | "refill" | "billing" | "question" | "transfer" | "other",
  "language": "en" | "es" | "other",
  "common_phrases": ["list of notable phrases the caller or receptionist used"],
  "receptionist_approach": "description of how the receptionist handled the call — tone, strategy, phrases",
  "info_collected": ["name", "dob", "insurance", "phone", "reason", "..."],
  "call_outcome": "booked" | "transferred" | "callback" | "voicemail" | "resolved" | "unresolved",
  "difficulty_points": ["list of any difficulties or confusion during the call"],
  "insurance_mentions": ["list of insurance carrier names mentioned, e.g. MetroPlus, Fidelis"],
  "appointment_type_mentions": ["list of appointment types mentioned, e.g. follow-up, new patient"],
  "caller_sentiment": "positive" | "neutral" | "frustrated" | "confused",
  "summary": "1-2 sentence summary of the call"
}

Be precise and factual. Only include information actually present in the transcript.
If something is unclear or not mentioned, use empty lists or "other"/"neutral" as appropriate."""

AGGREGATION_SYSTEM_PROMPT = """You are an expert data analyst for a medical office AI receptionist training system.
You are given analysis results from multiple real call recordings at this practice.

Aggregate these individual call analyses into a comprehensive summary of patterns and insights.
This will be used to calibrate the AI receptionist.

Return JSON with these fields:
{
  "intent_distribution": {"booking": 70, "billing": 15, "refill": 10, "other": 5},
  "language_distribution": {"en": 40, "es": 60},
  "common_phrases_en": ["list of frequently used English phrases by callers and receptionist"],
  "common_phrases_es": ["list of frequently used Spanish phrases by callers and receptionist"],
  "common_questions": ["list of frequently asked questions by callers"],
  "insurance_carriers": [{"name": "MetroPlus", "frequency": 12}, {"name": "Fidelis", "frequency": 8}],
  "appointment_types": [{"type": "follow-up", "frequency": 15}, {"type": "new patient", "frequency": 10}],
  "receptionist_patterns": ["list of effective patterns the receptionist uses — greetings, strategies, phrases"],
  "difficulty_areas": ["list of common difficult scenarios and how they were handled"],
  "caller_demographics": "observations about typical caller behavior, language preferences, needs",
  "recommendations": ["list of specific recommendations for the AI receptionist based on these patterns"]
}

All frequency/distribution values should be percentages or counts as appropriate.
Focus on actionable patterns that will help the AI receptionist serve this practice's patients."""

PROMPT_GENERATION_SYSTEM_PROMPT = """You are an expert prompt engineer specializing in AI medical receptionists.

You are given:
1. The CURRENT system prompt that is LIVE in production — this is the BASE
2. Aggregated insights from real call recordings at this practice

Your task: ENHANCE the current prompt by weaving in learnings from the call recordings.

CRITICAL RULES:
- The current prompt is the FOUNDATION. You MUST preserve its ENTIRE structure, identity,
  personality, office info, tool-calling instructions, booking flow, transfer rules, and all
  specific details (doctor name, hours, appointment types, insurance list, etc.)
- DO NOT rewrite from scratch. DO NOT create a generic prompt. KEEP the existing prompt
  and ADD/REFINE sections based on the call recording insights.
- Keep the SAME character name, office identity, and speaking style
- Keep ALL existing sections and their content — only add, refine, or expand
- Keep ALL tool call references (save_caller_info, verify_insurance, check_availability, etc.)

What to ADD or ENHANCE based on insights:
- Add commonly heard caller phrases to help recognition
- Add any new insurance carriers mentioned in calls that aren't already listed
- Add any new appointment types observed in calls
- Enhance Spanish phrases based on actual bilingual patterns observed
- Add specific handling for difficulty areas identified in the recordings
- Incorporate effective receptionist strategies and communication patterns
- Add tips for common caller intents and how to handle them

What NOT to change:
- The assistant's name and identity
- Office hours, doctor info, appointment types already listed
- The booking flow steps
- Tool call instructions (save_caller_info, verify_insurance, etc.)
- Transfer rules
- Emergency protocols
- The overall structure and formatting

Output the complete enhanced system prompt text only. No JSON wrapping, no explanations — just the prompt."""


# ---------------------------------------------------------------------------
# 1. Audio Transcription (OpenAI Whisper)
# ---------------------------------------------------------------------------

async def transcribe_audio(
    file_bytes: bytes,
    filename: str,
    mime_type: str,
) -> tuple[str, str, float | None]:
    """
    Send audio to OpenAI Whisper API for transcription.

    Args:
        file_bytes: Raw audio file bytes.
        filename: Original filename (used for the multipart upload).
        mime_type: MIME type of the audio file (e.g. audio/mpeg, audio/wav).

    Returns:
        Tuple of (transcript_text, detected_language, duration_seconds).

    Raises:
        ValueError: If the file exceeds the 25 MB limit or no API key is configured.
        httpx.HTTPStatusError: If the Whisper API returns an error.
    """
    if len(file_bytes) > _WHISPER_MAX_FILE_SIZE:
        raise ValueError(
            f"Audio file too large: {len(file_bytes)} bytes "
            f"(max {_WHISPER_MAX_FILE_SIZE // (1024 * 1024)} MB)"
        )

    api_key = get_settings().OPENAI_API_KEY
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured")

    client = get_http_client()

    # Use verbose_json to get language detection and duration
    resp = await client.post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {api_key}"},
        files={"file": (filename, file_bytes, mime_type)},
        data={
            "model": "whisper-1",
            "response_format": "verbose_json",
        },
        timeout=_WHISPER_TIMEOUT,
    )
    resp.raise_for_status()

    data = resp.json()
    transcript = data.get("text", "")
    language = data.get("language", "unknown")
    duration = data.get("duration")

    # Normalize common language codes
    language_map = {
        "english": "en",
        "spanish": "es",
        "greek": "el",
    }
    language = language_map.get(language.lower(), language) if language else "unknown"

    logger.info(
        "training_service: transcribed '%s' — %d chars, lang=%s, duration=%.1fs",
        filename,
        len(transcript),
        language,
        duration or 0,
    )

    return transcript, language, duration


# ---------------------------------------------------------------------------
# 2. Transcript Analysis (GPT-4o-mini)
# ---------------------------------------------------------------------------

async def analyze_transcript(transcript: str, language: str) -> dict | None:
    """
    Analyze a call transcript using GPT-4o-mini to extract structured patterns.

    Args:
        transcript: Full text transcript from Whisper.
        language: Detected language code (en, es, etc.).

    Returns:
        Dict with structured analysis fields, or None if analysis fails.
    """
    if not transcript or not transcript.strip():
        logger.warning("training_service: empty transcript, skipping analysis")
        return None

    # Truncate very long transcripts to stay within context limits
    max_chars = 12000
    truncated = transcript[:max_chars]
    if len(transcript) > max_chars:
        truncated += "\n\n[... transcript truncated for analysis ...]"

    user_prompt = (
        f"Detected language: {language}\n\n"
        f"Call transcript:\n{truncated}"
    )

    result = await _call_llm(
        TRANSCRIPT_ANALYSIS_SYSTEM_PROMPT,
        user_prompt,
        json_mode=True,
    )

    if result and isinstance(result, dict):
        logger.info(
            "training_service: analyzed transcript — intent=%s, sentiment=%s, outcome=%s",
            result.get("caller_intent", "unknown"),
            result.get("caller_sentiment", "unknown"),
            result.get("call_outcome", "unknown"),
        )
        return result

    logger.warning("training_service: transcript analysis returned no usable result")
    return None


# ---------------------------------------------------------------------------
# 3. Per-Recording Processing
# ---------------------------------------------------------------------------

async def transcribe_and_store(
    db: AsyncSession,
    recording_id: UUID,
    file_bytes: bytes,
    filename: str,
    mime_type: str,
) -> None:
    """
    Transcribe audio bytes via Whisper and store results on the recording.

    Called during the upload flow for each file. Updates the recording status
    to 'transcribed' on success or 'failed' on error.

    Args:
        db: Async database session.
        recording_id: UUID of the TrainingRecording row.
        file_bytes: Raw audio file bytes.
        filename: Original filename.
        mime_type: MIME type of the audio.
    """
    result = await db.execute(
        select(TrainingRecording).where(TrainingRecording.id == recording_id)
    )
    recording = result.scalar_one_or_none()
    if not recording:
        logger.error("training_service: recording %s not found", recording_id)
        return

    try:
        # Mark as transcribing
        recording.status = "transcribing"
        await db.flush()

        transcript, language, duration = await transcribe_audio(
            file_bytes, filename, mime_type,
        )

        recording.transcript = transcript
        recording.language_detected = language
        recording.duration_seconds = duration
        recording.status = "transcribed"
        await db.flush()

        logger.info(
            "training_service: recording %s transcribed — %d chars, lang=%s",
            recording_id, len(transcript), language,
        )

    except Exception as exc:
        logger.error(
            "training_service: transcription failed for recording %s: %s",
            recording_id, exc,
        )
        recording.status = "failed"
        recording.error_message = f"Transcription failed: {exc}"
        await db.flush()


async def analyze_recording(db: AsyncSession, recording_id: UUID) -> None:
    """
    Analyze a transcribed recording with GPT-4o-mini.

    Expects the recording to already have a transcript. Updates the recording
    status to 'completed' on success or 'failed' on error.

    Args:
        db: Async database session.
        recording_id: UUID of the TrainingRecording row.
    """
    result = await db.execute(
        select(TrainingRecording).where(TrainingRecording.id == recording_id)
    )
    recording = result.scalar_one_or_none()
    if not recording:
        logger.error("training_service: recording %s not found", recording_id)
        return

    if not recording.transcript:
        logger.warning(
            "training_service: recording %s has no transcript, cannot analyze",
            recording_id,
        )
        recording.status = "failed"
        recording.error_message = "No transcript available for analysis"
        await db.flush()
        return

    try:
        recording.status = "analyzing"
        await db.flush()

        analysis = await analyze_transcript(
            recording.transcript,
            recording.language_detected or "unknown",
        )

        if analysis:
            recording.analysis = analysis
            recording.status = "completed"
        else:
            recording.status = "failed"
            recording.error_message = "Analysis returned no results"

        await db.flush()

        logger.info(
            "training_service: recording %s analysis %s",
            recording_id,
            "completed" if analysis else "failed (empty result)",
        )

    except Exception as exc:
        logger.error(
            "training_service: analysis failed for recording %s: %s",
            recording_id, exc,
        )
        recording.status = "failed"
        recording.error_message = f"Analysis failed: {exc}"
        await db.flush()


# ---------------------------------------------------------------------------
# 4. Session Processing
# ---------------------------------------------------------------------------

async def process_session(db: AsyncSession, session_id: UUID) -> None:
    """
    Process all recordings in a training session.

    For each recording that has been transcribed but not yet analyzed, runs
    GPT-4o-mini analysis. After all recordings are processed, aggregates
    the insights across the session.

    Args:
        db: Async database session.
        session_id: UUID of the TrainingSession.
    """
    result = await db.execute(
        select(TrainingSession).where(TrainingSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        logger.error("training_service: session %s not found", session_id)
        return

    try:
        session.status = "processing"
        await db.flush()

        # Fetch all recordings that need analysis (transcribed but not yet analyzed)
        recs_result = await db.execute(
            select(TrainingRecording).where(
                TrainingRecording.session_id == session_id,
                TrainingRecording.status == "transcribed",
            )
        )
        recordings_to_analyze = recs_result.scalars().all()

        logger.info(
            "training_service: session %s — %d recordings to analyze",
            session_id, len(recordings_to_analyze),
        )

        for recording in recordings_to_analyze:
            try:
                await analyze_recording(db, recording.id)
                session.processed_count += 1
                await db.commit()
            except Exception as exc:
                logger.error(
                    "training_service: failed to analyze recording %s in session %s: %s",
                    recording.id, session_id, exc,
                )
                await db.rollback()
                # Re-fetch session after rollback
                result = await db.execute(
                    select(TrainingSession).where(TrainingSession.id == session_id)
                )
                session = result.scalar_one_or_none()
                if not session:
                    return

        # Aggregate insights across all completed recordings
        await aggregate_session_insights(db, session_id)

        # Re-fetch session to get latest state
        result = await db.execute(
            select(TrainingSession).where(TrainingSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if session:
            session.status = "completed"
            session.completed_at = datetime.now(timezone.utc)
            await db.flush()

        logger.info("training_service: session %s processing completed", session_id)

    except Exception as exc:
        logger.error(
            "training_service: session %s processing failed: %s",
            session_id, exc,
        )
        try:
            result = await db.execute(
                select(TrainingSession).where(TrainingSession.id == session_id)
            )
            session = result.scalar_one_or_none()
            if session:
                session.status = "failed"
                await db.flush()
        except Exception:
            logger.error("training_service: could not mark session %s as failed", session_id)


# ---------------------------------------------------------------------------
# 5. Insight Aggregation
# ---------------------------------------------------------------------------

async def aggregate_session_insights(
    db: AsyncSession,
    session_id: UUID,
) -> dict | None:
    """
    Aggregate analysis from all completed recordings in a session.

    Collects individual recording analyses and uses GPT-4o-mini to synthesize
    a comprehensive summary of patterns, demographics, and recommendations.

    Args:
        db: Async database session.
        session_id: UUID of the TrainingSession.

    Returns:
        Dict with aggregated insights, or None if aggregation fails.
    """
    # Fetch all completed recordings with analysis data
    result = await db.execute(
        select(TrainingRecording).where(
            TrainingRecording.session_id == session_id,
            TrainingRecording.status == "completed",
            TrainingRecording.analysis.isnot(None),
        )
    )
    recordings = result.scalars().all()

    if not recordings:
        logger.warning(
            "training_service: no completed recordings in session %s for aggregation",
            session_id,
        )
        return None

    # Build the list of individual analyses for the LLM
    analyses = []
    for rec in recordings:
        entry = dict(rec.analysis) if rec.analysis else {}
        entry["filename"] = rec.original_filename
        entry["language_detected"] = rec.language_detected
        entry["duration_seconds"] = rec.duration_seconds
        analyses.append(entry)

    user_prompt = (
        f"Total recordings analyzed: {len(analyses)}\n\n"
        f"Individual call analyses:\n{json.dumps(analyses, indent=2, default=str)}"
    )

    # Truncate if the payload is very large
    if len(user_prompt) > 30000:
        user_prompt = user_prompt[:30000] + "\n\n[... truncated due to length ...]"

    insights = await _call_llm(
        AGGREGATION_SYSTEM_PROMPT,
        user_prompt,
        json_mode=True,
    )

    if not insights or not isinstance(insights, dict):
        logger.warning(
            "training_service: aggregation for session %s returned no usable result",
            session_id,
        )
        return None

    # Store on the session
    session_result = await db.execute(
        select(TrainingSession).where(TrainingSession.id == session_id)
    )
    session = session_result.scalar_one_or_none()
    if session:
        session.aggregated_insights = insights
        await db.flush()

    logger.info(
        "training_service: aggregated insights for session %s — %d recordings, %d recommendations",
        session_id,
        len(recordings),
        len(insights.get("recommendations", [])),
    )

    return insights


# ---------------------------------------------------------------------------
# 6. Prompt Generation
# ---------------------------------------------------------------------------

async def generate_training_prompt(
    db: AsyncSession,
    session_id: UUID,
) -> str | None:
    """
    Generate an optimized system prompt based on session insights.

    Takes the current system prompt and the aggregated insights, then asks
    GPT-4o-mini to produce an improved prompt incorporating the learnings.

    Args:
        db: Async database session.
        session_id: UUID of the TrainingSession.

    Returns:
        The generated prompt text, or None if generation fails.
    """
    # Fetch session with insights
    result = await db.execute(
        select(TrainingSession).where(TrainingSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        logger.error("training_service: session %s not found", session_id)
        return None

    if not session.aggregated_insights:
        logger.warning(
            "training_service: session %s has no aggregated insights, cannot generate prompt",
            session_id,
        )
        return None

    # Fetch the current system prompt — try multiple sources in priority order:
    # 1. Live Vapi assistant (most accurate, the actual prompt in production)
    # 2. PracticeConfig fields
    # 3. Active PromptVersion record
    config_result = await db.execute(
        select(PracticeConfig).where(
            PracticeConfig.practice_id == session.practice_id
        )
    )
    config = config_result.scalar_one_or_none()

    current_prompt = None

    # Priority 1: Fetch live prompt from Vapi assistant
    if config and config.vapi_assistant_id:
        vapi_key = getattr(config, "vapi_api_key", None) or get_settings().VAPI_API_KEY
        if vapi_key:
            try:
                client = get_http_client()
                resp = await client.get(
                    f"https://api.vapi.ai/assistant/{config.vapi_assistant_id}",
                    headers={"Authorization": f"Bearer {vapi_key}"},
                    timeout=10,
                )
                resp.raise_for_status()
                vapi_data = resp.json()
                messages = vapi_data.get("model", {}).get("messages", [])
                for msg in messages:
                    if msg.get("role") == "system" and msg.get("content"):
                        current_prompt = msg["content"]
                        logger.info(
                            "training_service: fetched live prompt from Vapi (%d chars)",
                            len(current_prompt),
                        )
                        break
            except Exception as exc:
                logger.warning(
                    "training_service: failed to fetch live Vapi prompt: %s", exc
                )

    # Priority 2: PracticeConfig fields
    if not current_prompt and config:
        current_prompt = config.vapi_system_prompt or getattr(config, "system_prompt", None)

    # Priority 3: Active PromptVersion
    if not current_prompt:
        from app.models.feedback import PromptVersion
        pv_result = await db.execute(
            select(PromptVersion.prompt_text)
            .where(
                PromptVersion.practice_id == session.practice_id,
                PromptVersion.is_active == True,
            )
            .limit(1)
        )
        current_prompt = pv_result.scalar_one_or_none()

    if not current_prompt:
        current_prompt = "(No existing system prompt found. Generate a complete prompt from scratch.)"

    # Build the user prompt for the meta-prompt generation
    insights_text = json.dumps(session.aggregated_insights, indent=2, default=str)

    # Truncate if necessary
    max_prompt_chars = 6000
    max_insights_chars = 10000
    current_prompt_truncated = current_prompt[:max_prompt_chars]
    if len(current_prompt) > max_prompt_chars:
        current_prompt_truncated += "\n[... prompt truncated ...]"
    insights_truncated = insights_text[:max_insights_chars]
    if len(insights_text) > max_insights_chars:
        insights_truncated += "\n[... insights truncated ...]"

    user_prompt = (
        f"CURRENT SYSTEM PROMPT:\n"
        f"---\n{current_prompt_truncated}\n---\n\n"
        f"AGGREGATED INSIGHTS FROM {session.total_recordings} CALL RECORDINGS:\n"
        f"---\n{insights_truncated}\n---\n\n"
        f"Generate the complete improved system prompt."
    )

    # Use text mode (not JSON) since we want a raw prompt string
    generated = await _call_llm(
        PROMPT_GENERATION_SYSTEM_PROMPT,
        user_prompt,
        json_mode=False,
    )

    if not generated or not isinstance(generated, str):
        logger.warning(
            "training_service: prompt generation for session %s returned no usable result",
            session_id,
        )
        return None

    # Clean up any accidental markdown fencing the LLM might add
    generated = generated.strip()
    if generated.startswith("```"):
        lines = generated.split("\n")
        # Remove first line (```...) and last line (```)
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        generated = "\n".join(lines).strip()

    # Store on the session
    session.generated_prompt = generated
    session.current_prompt_snapshot = current_prompt
    await db.commit()

    logger.info(
        "training_service: generated prompt for session %s — %d chars",
        session_id, len(generated),
    )

    return generated


# ---------------------------------------------------------------------------
# 7. Apply the Generated Prompt
# ---------------------------------------------------------------------------

async def apply_training_prompt(
    db: AsyncSession,
    session_id: UUID,
    practice_id: UUID,
    prompt_override: str | None = None,
    push_to_vapi: bool = True,
) -> dict:
    """
    Apply the generated (or manually overridden) prompt to the practice.

    Creates a versioned PromptVersion record and optionally pushes the prompt
    to the Vapi assistant.

    Args:
        db: Async database session.
        session_id: UUID of the TrainingSession.
        practice_id: UUID of the Practice.
        prompt_override: If provided, uses this text instead of session.generated_prompt.
        push_to_vapi: Whether to push the prompt to Vapi (default True).

    Returns:
        Dict with success status, version number, and push result.
    """
    # Fetch session
    result = await db.execute(
        select(TrainingSession).where(TrainingSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        return {"success": False, "error": "Session not found"}

    prompt_text = prompt_override or session.generated_prompt
    if not prompt_text:
        return {"success": False, "error": "No prompt available to apply"}

    try:
        # Create versioned prompt record
        change_reason = (
            f"Training-based prompt from session '{session.name or session_id}' "
            f"({session.total_recordings} recordings analyzed)"
        )

        # Compute a simple diff summary
        change_diff = None
        if session.current_prompt_snapshot:
            old_len = len(session.current_prompt_snapshot)
            new_len = len(prompt_text)
            change_diff = (
                f"Training prompt generation: "
                f"old={old_len} chars, new={new_len} chars, "
                f"delta={new_len - old_len:+d} chars"
            )

        version = await apply_prompt_improvement(
            db=db,
            practice_id=practice_id,
            new_prompt=prompt_text,
            change_reason=change_reason,
            change_diff=change_diff,
        )

        pushed = False
        if push_to_vapi:
            pushed = await push_prompt_to_vapi(practice_id, prompt_text, db)

        await db.commit()

        logger.info(
            "training_service: applied training prompt v%d for practice %s (pushed=%s)",
            version.version, practice_id, pushed,
        )

        return {
            "success": True,
            "version": version.version,
            "pushed_to_vapi": pushed,
        }

    except Exception as exc:
        logger.error(
            "training_service: failed to apply prompt for session %s: %s",
            session_id, exc,
        )
        return {"success": False, "error": str(exc)}
