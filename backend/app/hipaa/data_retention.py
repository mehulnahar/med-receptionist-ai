"""
HIPAA Data Retention — automated purge of expired PHI data.

Configurable per-practice retention periods:
  - Call recordings: default 365 days
  - Call transcripts: default 365 days
  - Call records: default 2555 days (7 years — HIPAA minimum)
  - Audit logs: default 2555 days (7 years)

Runs nightly as a background task. All deletions are logged to the audit trail.
"""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DEFAULT_RECORDING_RETENTION_DAYS = 365
DEFAULT_TRANSCRIPT_RETENTION_DAYS = 365
DEFAULT_CALL_LOG_RETENTION_DAYS = 2555  # ~7 years
DEFAULT_AUDIT_LOG_RETENTION_DAYS = 2555


async def get_retention_config(session: AsyncSession, practice_id: UUID) -> dict:
    """Get retention config for a practice, or defaults."""
    result = await session.execute(
        text("SELECT * FROM data_retention_config WHERE practice_id = :pid"),
        {"pid": str(practice_id)},
    )
    row = result.fetchone()
    if row:
        return {
            "recording_retention_days": row.recording_retention_days or DEFAULT_RECORDING_RETENTION_DAYS,
            "transcript_retention_days": row.transcript_retention_days or DEFAULT_TRANSCRIPT_RETENTION_DAYS,
            "call_log_retention_days": row.call_log_retention_days or DEFAULT_CALL_LOG_RETENTION_DAYS,
            "audit_log_retention_days": row.audit_log_retention_days or DEFAULT_AUDIT_LOG_RETENTION_DAYS,
        }
    return {
        "recording_retention_days": DEFAULT_RECORDING_RETENTION_DAYS,
        "transcript_retention_days": DEFAULT_TRANSCRIPT_RETENTION_DAYS,
        "call_log_retention_days": DEFAULT_CALL_LOG_RETENTION_DAYS,
        "audit_log_retention_days": DEFAULT_AUDIT_LOG_RETENTION_DAYS,
    }


async def purge_expired_recordings(
    session: AsyncSession,
    practice_id: UUID,
    retention_days: int,
) -> int:
    """Null out recording URLs older than retention period. Returns count."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    result = await session.execute(
        text("""
            UPDATE calls SET recording_url = NULL
            WHERE practice_id = :pid
              AND recording_url IS NOT NULL
              AND created_at < :cutoff
        """),
        {"pid": str(practice_id), "cutoff": cutoff},
    )
    return result.rowcount or 0


async def purge_expired_transcripts(
    session: AsyncSession,
    practice_id: UUID,
    retention_days: int,
) -> int:
    """Null out transcripts and AI summaries older than retention period."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    result = await session.execute(
        text("""
            UPDATE calls
            SET transcription = NULL, ai_summary = NULL
            WHERE practice_id = :pid
              AND (transcription IS NOT NULL OR ai_summary IS NOT NULL)
              AND created_at < :cutoff
        """),
        {"pid": str(practice_id), "cutoff": cutoff},
    )
    return result.rowcount or 0


async def purge_expired_call_logs(
    session: AsyncSession,
    practice_id: UUID,
    retention_days: int,
) -> int:
    """Delete call records older than retention period."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    result = await session.execute(
        text("""
            DELETE FROM calls
            WHERE practice_id = :pid
              AND created_at < :cutoff
        """),
        {"pid": str(practice_id), "cutoff": cutoff},
    )
    return result.rowcount or 0


async def run_data_retention_purge(session: AsyncSession) -> dict:
    """Run data retention purge for all practices. Returns summary."""
    summary = {"practices_processed": 0, "recordings_purged": 0, "transcripts_purged": 0, "calls_deleted": 0}

    result = await session.execute(text("SELECT id FROM practices WHERE status = 'active'"))
    practices = result.fetchall()

    for row in practices:
        practice_id = row[0]
        config = await get_retention_config(session, practice_id)

        recordings = await purge_expired_recordings(session, practice_id, config["recording_retention_days"])
        transcripts = await purge_expired_transcripts(session, practice_id, config["transcript_retention_days"])
        calls = await purge_expired_call_logs(session, practice_id, config["call_log_retention_days"])

        summary["practices_processed"] += 1
        summary["recordings_purged"] += recordings
        summary["transcripts_purged"] += transcripts
        summary["calls_deleted"] += calls

        if recordings or transcripts or calls:
            logger.info(
                "data_retention: practice %s — purged %d recordings, %d transcripts, %d call logs",
                practice_id, recordings, transcripts, calls,
            )

    await session.commit()
    return summary
