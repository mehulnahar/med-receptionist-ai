"""
Training pipeline API endpoints for the AI Medical Receptionist.

Provides endpoints for:
- Creating and managing training sessions
- Uploading call recordings (audio files)
- Processing recordings (transcription + analysis)
- Viewing aggregated insights
- Generating and applying optimized system prompts
"""

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, status, BackgroundTasks
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.user import User
from app.models.training import TrainingSession, TrainingRecording
from app.middleware.auth import require_practice_admin, require_any_staff
from app.schemas.training import (
    TrainingSessionCreate,
    TrainingSessionResponse,
    TrainingSessionDetail,
    TrainingSessionListResponse,
    TrainingRecordingResponse,
    TrainingRecordingListResponse,
    TrainingInsightsResponse,
    GeneratedPromptResponse,
    ApplyPromptRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Max file size: 25 MB (OpenAI Whisper limit)
MAX_FILE_SIZE = 25 * 1024 * 1024
ALLOWED_MIME_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/wave", "audio/x-wav",
    "audio/mp4", "audio/m4a", "audio/x-m4a", "audio/ogg", "audio/webm",
    "audio/flac", "audio/x-flac",
}
# Also allow by extension since mime detection can be unreliable
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".webm", ".flac", ".mp4", ".mpeg"}


def _ensure_practice(user: User) -> UUID:
    if not user.practice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No practice associated with this user",
        )
    return user.practice_id


def _check_file_allowed(filename: str, content_type: str | None, size: int | None) -> None:
    """Validate uploaded file type and size."""
    import os
    ext = os.path.splitext(filename)[1].lower() if filename else ""

    if ext not in ALLOWED_EXTENSIONS and (content_type or "").lower() not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {content_type or ext}. Allowed: MP3, WAV, M4A, OGG, WebM, FLAC",
        )

    if size and size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large ({size / 1024 / 1024:.1f} MB). Maximum: 25 MB",
        )


# ---------------------------------------------------------------------------
# Sessions CRUD
# ---------------------------------------------------------------------------

@router.post("/sessions", response_model=TrainingSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: TrainingSessionCreate,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Create a new training session."""
    practice_id = _ensure_practice(current_user)

    session = TrainingSession(
        practice_id=practice_id,
        name=body.name or f"Training Session - {datetime.now(timezone.utc).strftime('%b %d, %Y')}",
        status="pending",
        total_recordings=0,
        processed_count=0,
        created_by=current_user.id,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    logger.info("Training session created: %s (practice=%s)", session.id, practice_id)
    return session


@router.get("/sessions", response_model=TrainingSessionListResponse)
async def list_sessions(
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """List all training sessions for the practice."""
    practice_id = _ensure_practice(current_user)

    result = await db.execute(
        select(TrainingSession)
        .where(TrainingSession.practice_id == practice_id)
        .order_by(desc(TrainingSession.created_at))
    )
    sessions = result.scalars().all()

    return TrainingSessionListResponse(
        sessions=[TrainingSessionResponse.model_validate(s) for s in sessions],
        total=len(sessions),
    )


@router.get("/sessions/{session_id}", response_model=TrainingSessionDetail)
async def get_session(
    session_id: UUID,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Get a training session with all recordings."""
    practice_id = _ensure_practice(current_user)

    result = await db.execute(
        select(TrainingSession)
        .options(selectinload(TrainingSession.recordings))
        .where(
            TrainingSession.id == session_id,
            TrainingSession.practice_id == practice_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Training session not found")

    return TrainingSessionDetail(
        id=session.id,
        name=session.name,
        status=session.status,
        total_recordings=session.total_recordings,
        processed_count=session.processed_count,
        created_at=session.created_at,
        completed_at=session.completed_at,
        aggregated_insights=session.aggregated_insights,
        generated_prompt=session.generated_prompt,
        current_prompt_snapshot=session.current_prompt_snapshot,
        recordings=[TrainingRecordingResponse.model_validate(r) for r in session.recordings],
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Delete a training session (only if not currently processing)."""
    practice_id = _ensure_practice(current_user)

    result = await db.execute(
        select(TrainingSession).where(
            TrainingSession.id == session_id,
            TrainingSession.practice_id == practice_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Training session not found")

    if session.status == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a session that is currently processing",
        )

    await db.delete(session)
    await db.commit()
    logger.info("Training session deleted: %s", session_id)


# ---------------------------------------------------------------------------
# Bulk Import Text Transcripts (for HuggingFace / pre-transcribed data)
# ---------------------------------------------------------------------------

from pydantic import BaseModel as _BaseModel
from typing import List as _List


class _TranscriptItem(_BaseModel):
    filename: str
    transcript: str
    language: str = "en"
    category: str = "Unknown"


class _BulkImportRequest(_BaseModel):
    transcripts: _List[_TranscriptItem]


@router.post("/sessions/{session_id}/import-transcripts")
async def import_transcripts(
    session_id: UUID,
    body: _BulkImportRequest,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """
    Bulk-import pre-transcribed text transcripts into a training session.
    Skips Whisper — recordings are created with status='transcribed' directly.
    """
    practice_id = _ensure_practice(current_user)

    # Verify session
    result = await db.execute(
        select(TrainingSession).where(
            TrainingSession.id == session_id,
            TrainingSession.practice_id == practice_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Training session not found")

    if session.status == "processing":
        raise HTTPException(status_code=409, detail="Cannot import to a session that is currently processing")

    imported = 0
    for item in body.transcripts:
        if not item.transcript or len(item.transcript) < 50:
            continue

        recording = TrainingRecording(
            practice_id=practice_id,
            session_id=session_id,
            original_filename=item.filename,
            file_size_bytes=len(item.transcript.encode("utf-8")),
            mime_type="text/plain",
            status="transcribed",  # Skip Whisper — already have text
            transcript=item.transcript,
            language_detected=item.language,
            duration_seconds=None,
            uploaded_by=current_user.id,
        )
        db.add(recording)
        imported += 1

    # Update session counts
    session.total_recordings = (session.total_recordings or 0) + imported
    if session.status == "completed":
        session.status = "pending"
    await db.commit()

    logger.info(
        "Bulk imported %d transcripts into session %s (practice=%s)",
        imported, session_id, practice_id,
    )

    return {"imported": imported, "session_id": str(session_id)}


# ---------------------------------------------------------------------------
# Upload Recordings
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/upload", response_model=TrainingRecordingListResponse)
async def upload_recordings(
    session_id: UUID,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(..., description="Audio files (.mp3, .wav, .m4a, .ogg, .webm, .flac)"),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload one or more audio recordings to a training session.

    Files are immediately streamed to OpenAI Whisper for transcription.
    The audio bytes are NOT stored permanently (Railway ephemeral disk).
    """
    practice_id = _ensure_practice(current_user)

    # Verify session exists and is in valid state
    result = await db.execute(
        select(TrainingSession).where(
            TrainingSession.id == session_id,
            TrainingSession.practice_id == practice_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Training session not found")

    if session.status == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot upload to a session that is currently processing",
        )

    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 files per upload")

    recordings_created = []

    for upload_file in files:
        # Validate file type
        _check_file_allowed(upload_file.filename or "", upload_file.content_type, upload_file.size)

        # Read file bytes into memory
        file_bytes = await upload_file.read()
        file_size = len(file_bytes)

        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File '{upload_file.filename}' is too large ({file_size / 1024 / 1024:.1f} MB). Max: 25 MB",
            )

        if file_size == 0:
            continue  # Skip empty files

        # Create recording record
        recording = TrainingRecording(
            practice_id=practice_id,
            session_id=session_id,
            original_filename=upload_file.filename or "unknown",
            file_size_bytes=file_size,
            mime_type=upload_file.content_type,
            status="uploaded",
            uploaded_by=current_user.id,
        )
        db.add(recording)
        await db.flush()  # Get the ID

        recordings_created.append((recording.id, file_bytes, upload_file.filename or "unknown", upload_file.content_type or "audio/mpeg"))

    # Update session recording count
    session.total_recordings = (session.total_recordings or 0) + len(recordings_created)
    if session.status == "completed":
        session.status = "pending"  # Reset if adding more files
    await db.commit()

    # Schedule background transcription for each recording
    for rec_id, f_bytes, f_name, f_mime in recordings_created:
        background_tasks.add_task(_transcribe_background, rec_id, f_bytes, f_name, f_mime)

    # Refresh recordings for response
    result = await db.execute(
        select(TrainingRecording)
        .where(TrainingRecording.session_id == session_id)
        .order_by(TrainingRecording.created_at)
    )
    all_recordings = result.scalars().all()

    return TrainingRecordingListResponse(
        recordings=[TrainingRecordingResponse.model_validate(r) for r in all_recordings],
        total=len(all_recordings),
    )


async def _transcribe_background(recording_id: UUID, file_bytes: bytes, filename: str, mime_type: str):
    """Background task to transcribe a single recording."""
    from app.database import AsyncSessionLocal
    from app.services.training_service import transcribe_and_store

    async with AsyncSessionLocal() as db:
        try:
            await transcribe_and_store(db, recording_id, file_bytes, filename, mime_type)
        except Exception as e:
            logger.error("Background transcription failed for recording %s: %s", recording_id, e)
            # Update status to failed
            result = await db.execute(
                select(TrainingRecording).where(TrainingRecording.id == recording_id)
            )
            rec = result.scalar_one_or_none()
            if rec:
                rec.status = "failed"
                rec.error_message = str(e)[:500]
                await db.commit()


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/process")
async def start_processing(
    session_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Start analyzing all transcribed recordings in the session."""
    practice_id = _ensure_practice(current_user)

    result = await db.execute(
        select(TrainingSession).where(
            TrainingSession.id == session_id,
            TrainingSession.practice_id == practice_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Training session not found")

    if session.status == "processing":
        raise HTTPException(status_code=409, detail="Session is already being processed")

    # Check we have transcribed recordings to analyze
    result = await db.execute(
        select(func.count(TrainingRecording.id)).where(
            TrainingRecording.session_id == session_id,
            TrainingRecording.transcript.isnot(None),
            TrainingRecording.status.in_(["transcribed", "uploaded"]),
        )
    )
    ready_count = result.scalar() or 0

    if ready_count == 0:
        raise HTTPException(
            status_code=400,
            detail="No transcribed recordings ready for analysis. Wait for uploads to finish transcribing.",
        )

    session.status = "processing"
    session.processed_count = 0
    await db.commit()

    background_tasks.add_task(_process_session_background, session_id)

    return {"message": f"Processing started for {ready_count} recordings", "session_id": str(session_id)}


async def _process_session_background(session_id: UUID):
    """Background task to process all recordings in a session."""
    from app.database import AsyncSessionLocal
    from app.services.training_service import process_session

    async with AsyncSessionLocal() as db:
        try:
            await process_session(db, session_id)
        except Exception as e:
            logger.error("Background session processing failed for %s: %s", session_id, e)
            result = await db.execute(
                select(TrainingSession).where(TrainingSession.id == session_id)
            )
            session = result.scalar_one_or_none()
            if session:
                session.status = "failed"
                await db.commit()


# ---------------------------------------------------------------------------
# Recordings List
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}/recordings", response_model=TrainingRecordingListResponse)
async def list_recordings(
    session_id: UUID,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """List all recordings in a session with their status."""
    practice_id = _ensure_practice(current_user)

    # Verify session belongs to practice
    sess_result = await db.execute(
        select(TrainingSession.id).where(
            TrainingSession.id == session_id,
            TrainingSession.practice_id == practice_id,
        )
    )
    if not sess_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Training session not found")

    result = await db.execute(
        select(TrainingRecording)
        .where(TrainingRecording.session_id == session_id)
        .order_by(TrainingRecording.created_at)
    )
    recordings = result.scalars().all()

    return TrainingRecordingListResponse(
        recordings=[TrainingRecordingResponse.model_validate(r) for r in recordings],
        total=len(recordings),
    )


# ---------------------------------------------------------------------------
# Retry Aggregation (for stuck sessions)
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/retry-aggregation")
async def retry_aggregation(
    session_id: UUID,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Re-run insight aggregation for a stuck session where all recordings are done."""
    practice_id = _ensure_practice(current_user)

    result = await db.execute(
        select(TrainingSession).where(
            TrainingSession.id == session_id,
            TrainingSession.practice_id == practice_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Training session not found")

    from app.services.training_service import aggregate_session_insights, generate_training_prompt

    # Run aggregation
    insights = await aggregate_session_insights(db, session_id)

    # Generate prompt if insights succeeded
    prompt = None
    if insights:
        prompt = await generate_training_prompt(db, session_id)

    # Mark session completed
    result = await db.execute(
        select(TrainingSession).where(TrainingSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session:
        session.status = "completed"
        session.completed_at = datetime.now(timezone.utc)
        await db.commit()

    return {
        "status": "completed",
        "has_insights": bool(insights),
        "has_prompt": bool(prompt),
        "prompt_length": len(prompt) if prompt else 0,
    }


# ---------------------------------------------------------------------------
# Insights & Prompt Generation
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}/insights", response_model=TrainingInsightsResponse)
async def get_insights(
    session_id: UUID,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregated insights from the training session."""
    practice_id = _ensure_practice(current_user)

    result = await db.execute(
        select(TrainingSession).where(
            TrainingSession.id == session_id,
            TrainingSession.practice_id == practice_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Training session not found")

    return TrainingInsightsResponse(
        session_id=session.id,
        status=session.status,
        total_recordings=session.total_recordings,
        processed_count=session.processed_count,
        insights=session.aggregated_insights,
    )


@router.post("/sessions/{session_id}/generate-prompt", response_model=GeneratedPromptResponse)
async def generate_prompt(
    session_id: UUID,
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Generate an optimized system prompt based on session insights."""
    practice_id = _ensure_practice(current_user)

    result = await db.execute(
        select(TrainingSession).where(
            TrainingSession.id == session_id,
            TrainingSession.practice_id == practice_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Training session not found")

    if not session.aggregated_insights:
        raise HTTPException(
            status_code=400,
            detail="No aggregated insights available. Process the recordings first.",
        )

    from app.services.training_service import generate_training_prompt
    prompt = await generate_training_prompt(db, session_id)

    return GeneratedPromptResponse(
        session_id=session.id,
        generated_prompt=prompt,
        current_prompt=session.current_prompt_snapshot,
    )


@router.post("/sessions/{session_id}/apply-prompt")
async def apply_prompt(
    session_id: UUID,
    body: ApplyPromptRequest = ApplyPromptRequest(),
    current_user: User = Depends(require_any_staff),
    db: AsyncSession = Depends(get_db),
):
    """Apply the generated (or manually edited) prompt to the practice and optionally push to Vapi."""
    practice_id = _ensure_practice(current_user)

    result = await db.execute(
        select(TrainingSession).where(
            TrainingSession.id == session_id,
            TrainingSession.practice_id == practice_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Training session not found")

    prompt_to_apply = body.prompt_override or session.generated_prompt
    if not prompt_to_apply:
        raise HTTPException(
            status_code=400,
            detail="No prompt available. Generate a prompt first, or provide a prompt_override.",
        )

    from app.services.training_service import apply_training_prompt
    result_data = await apply_training_prompt(
        db=db,
        session_id=session_id,
        practice_id=practice_id,
        prompt_override=body.prompt_override,
        push_to_vapi=body.push_to_vapi,
    )

    return result_data
