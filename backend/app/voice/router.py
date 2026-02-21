"""
Intelligent model routing — routes queries to Haiku or Sonnet based on complexity.

60-70% of queries go to Haiku (fast, cheap), 30-40% to Sonnet (complex).
Emergency keywords bypass LLM entirely.
"""

import logging
import re
from enum import Enum

from app.voice.triage import detect_urgency, UrgencyLevel

logger = logging.getLogger(__name__)


class ModelTier(str, Enum):
    HAIKU = "haiku"
    SONNET = "sonnet"
    EMERGENCY = "emergency"  # No LLM needed


# Patterns that indicate complex queries requiring Sonnet
SONNET_PATTERNS = [
    r"\binsurance\b.*\b(verify|check|eligibility|coverage)\b",
    r"\b(multiple|two|several)\s*(insurance|coverage)\b",
    r"\bworkers?\s*comp\b",
    r"\bno\s*fault\b",
    r"\baccident\b",
    r"\binjur(y|ed|ies)\b",
    r"\brefill\b.*\b(prescription|medication|rx)\b",
    r"\b(billing|payment|charge|cost|fee|balance)\b",
    r"\b(complaint|unhappy|frustrated|upset|angry)\b",
    r"\b(transfer|speak|talk)\b.*\b(person|human|staff|doctor|nurse)\b",
    r"\b(medical\s*record|chart|history|results)\b",
    r"\b(referral|specialist|second\s*opinion)\b",
    r"\bnew\s*patient\b",  # New patient flow is multi-step
]

# Patterns that indicate simple queries suitable for Haiku
HAIKU_PATTERNS = [
    r"\b(hours|open|close|when)\b",
    r"\b(address|where|location|directions|parking)\b",
    r"\b(phone|number|fax|email)\b",
    r"\bappointment\b.*\b(cancel|confirm)\b",
    r"\b(yes|no|correct|right|that'?s?\s*right)\b",
    r"\b(thanks?|thank\s*you|okay|bye|goodbye)\b",
    r"\b(hi|hello|hey|good\s*(morning|afternoon|evening))\b",
    r"\bwhat\s*(time|day)\b.*\b(appointment|next)\b",
]

_SONNET_COMPILED = [re.compile(p, re.IGNORECASE) for p in SONNET_PATTERNS]
_HAIKU_COMPILED = [re.compile(p, re.IGNORECASE) for p in HAIKU_PATTERNS]


def classify_query(transcript: str, language: str = "en") -> ModelTier:
    """Classify a query to determine which model should handle it.

    Returns the recommended model tier.
    """
    if not transcript or not transcript.strip():
        return ModelTier.HAIKU

    # First check for emergencies (no LLM needed)
    triage = detect_urgency(transcript, language)
    if triage.level == UrgencyLevel.EMERGENCY:
        return ModelTier.EMERGENCY
    if triage.level == UrgencyLevel.HIGH:
        return ModelTier.SONNET

    text = transcript.lower()

    # Check for Sonnet patterns
    for pattern in _SONNET_COMPILED:
        if pattern.search(text):
            logger.debug("Query routed to Sonnet: pattern match")
            return ModelTier.SONNET

    # Check for Haiku patterns
    for pattern in _HAIKU_COMPILED:
        if pattern.search(text):
            logger.debug("Query routed to Haiku: simple pattern match")
            return ModelTier.HAIKU

    # Default: longer/ambiguous queries go to Sonnet
    word_count = len(text.split())
    if word_count > 20:
        return ModelTier.SONNET

    # Default to Haiku for medium-length unclassified queries
    return ModelTier.HAIKU
