"""
Emergency triage system — keyword detection BEFORE Claude processing.

Runs on raw Whisper transcript to detect emergency/urgent situations.
Must trigger within 2 seconds — no LLM needed for detection.
"""

import logging
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class UrgencyLevel(str, Enum):
    EMERGENCY = "emergency"      # Immediate transfer + 911 recommendation
    HIGH = "high"                # Escalate after current task
    NORMAL = "normal"            # Continue with AI
    LOW = "low"                  # FAQ / simple query


@dataclass
class TriageResult:
    level: UrgencyLevel
    matched_keyword: Optional[str]
    recommended_action: str
    message_to_caller: str
    detection_time_ms: float


# Emergency keywords — IMMEDIATE transfer (< 2 seconds)
EMERGENCY_KEYWORDS = [
    r"\bchest\s*pain\b",
    r"\bheart\s*attack\b",
    r"\bcan'?t\s*breathe\b",
    r"\bdifficulty\s*breathing\b",
    r"\bstroke\b",
    r"\bemergency\b",
    r"\bambulance\b",
    r"\b911\b",
    r"\bdying\b",
    r"\bsevere\s*pain\b",
    r"\bunconscious\b",
    r"\boverdose\b",
    r"\btoo\s*many\s*pills\b",
    r"\bpoison\b",
    r"\bbleeding\s*(a\s*lot|heavily|badly|profusely)\b",
    r"\bsuicid\w*\b",
    r"\bself\s*harm\b",
    r"\bcan'?t\s*feel\b",
    r"\bnumb\s*(face|arm|leg)\b",
    r"\bslurring\b",
    r"\bseizure\b",
    r"\ballergic\s*reaction\b",
    r"\banaphyla\w*\b",
    r"\bswelling\s*(throat|tongue|face)\b",
]

# High priority keywords — escalate after current task
HIGH_PRIORITY_KEYWORDS = [
    r"\bvery\s*sick\b",
    r"\breally\s*bad\b",
    r"\bgetting\s*worse\b",
    r"\bcan'?t\s*wait\b",
    r"\bworse\s*and\s*worse\b",
    r"\bhigh\s*fever\b",
    r"\bbeen\s*vomiting\b",
    r"\bchild\s*is\s*(very\s*)?(sick|ill)\b",
    r"\bbaby\s*is\s*(very\s*)?(sick|ill)\b",
    r"\bfainting\b",
    r"\bdizzy\s*(and|with)\b",
    r"\bblood\s*in\b",
]

# Pre-compiled patterns for performance
_EMERGENCY_PATTERNS = [re.compile(kw, re.IGNORECASE) for kw in EMERGENCY_KEYWORDS]
_HIGH_PATTERNS = [re.compile(kw, re.IGNORECASE) for kw in HIGH_PRIORITY_KEYWORDS]

# Emergency messages
EMERGENCY_MESSAGE_EN = (
    "I understand this is an emergency situation. I'm transferring you to our "
    "staff immediately. If you believe this is life-threatening, please also "
    "call 911 right away."
)
EMERGENCY_MESSAGE_ES = (
    "Entiendo que esta es una situacion de emergencia. Lo estoy transfiriendo "
    "a nuestro personal inmediatamente. Si cree que es una amenaza para la vida, "
    "por favor tambien llame al 911 de inmediato."
)
HIGH_PRIORITY_MESSAGE_EN = (
    "I understand you're not feeling well. Let me connect you with our staff "
    "who can help you right away."
)
HIGH_PRIORITY_MESSAGE_ES = (
    "Entiendo que no se siente bien. Permitame conectarlo con nuestro personal "
    "que puede ayudarlo de inmediato."
)


def detect_urgency(
    transcript: str,
    language: str = "en",
) -> TriageResult:
    """Detect urgency level from transcript text.

    This runs BEFORE Claude to catch emergencies immediately.
    Must complete in < 100ms (typically < 5ms).
    """
    start = time.monotonic()

    if not transcript or not transcript.strip():
        elapsed_ms = (time.monotonic() - start) * 1000
        return TriageResult(
            level=UrgencyLevel.NORMAL,
            matched_keyword=None,
            recommended_action="continue",
            message_to_caller="",
            detection_time_ms=elapsed_ms,
        )

    text_lower = transcript.lower()

    # Check emergency keywords first
    for pattern in _EMERGENCY_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            elapsed_ms = (time.monotonic() - start) * 1000
            msg = EMERGENCY_MESSAGE_ES if language == "es" else EMERGENCY_MESSAGE_EN
            logger.warning(
                "EMERGENCY TRIAGE: keyword='%s' in transcript (%.1fms)",
                match.group(), elapsed_ms,
            )
            return TriageResult(
                level=UrgencyLevel.EMERGENCY,
                matched_keyword=match.group(),
                recommended_action="immediate_transfer",
                message_to_caller=msg,
                detection_time_ms=elapsed_ms,
            )

    # Check high priority keywords
    for pattern in _HIGH_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            elapsed_ms = (time.monotonic() - start) * 1000
            msg = HIGH_PRIORITY_MESSAGE_ES if language == "es" else HIGH_PRIORITY_MESSAGE_EN
            logger.info(
                "HIGH PRIORITY TRIAGE: keyword='%s' in transcript (%.1fms)",
                match.group(), elapsed_ms,
            )
            return TriageResult(
                level=UrgencyLevel.HIGH,
                matched_keyword=match.group(),
                recommended_action="escalate_after_current",
                message_to_caller=msg,
                detection_time_ms=elapsed_ms,
            )

    elapsed_ms = (time.monotonic() - start) * 1000
    return TriageResult(
        level=UrgencyLevel.NORMAL,
        matched_keyword=None,
        recommended_action="continue",
        message_to_caller="",
        detection_time_ms=elapsed_ms,
    )


async def log_escalation_event(
    practice_id: str,
    call_id: str,
    triage_result: TriageResult,
    transcript_snippet: str,
) -> None:
    """Log an escalation event to the database for tracking."""
    try:
        from app.database import AsyncSessionLocal
        from sqlalchemy import text

        async with AsyncSessionLocal() as session:
            await session.execute(
                text("""
                    INSERT INTO escalation_events
                        (id, practice_id, call_id, urgency_level, matched_keyword,
                         transcript_snippet, detection_time_ms, created_at)
                    VALUES
                        (gen_random_uuid(), :practice_id, :call_id, :level,
                         :keyword, :snippet, :time_ms, NOW())
                """),
                {
                    "practice_id": practice_id,
                    "call_id": call_id,
                    "level": triage_result.level.value,
                    "keyword": triage_result.matched_keyword,
                    "snippet": transcript_snippet[:500],
                    "time_ms": triage_result.detection_time_ms,
                },
            )
            await session.commit()
    except Exception as e:
        logger.error("Failed to log escalation event: %s", e)
