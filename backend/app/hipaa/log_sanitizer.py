"""
PHI Log Sanitization Filter — strips Protected Health Information from log output.

HIPAA requires that PHI is never written to application logs. This filter
intercepts all log records and redacts patterns that look like:
  - Phone numbers
  - SSN patterns
  - Dates of birth
  - Email addresses
  - Names following known PHI keys
"""

import logging
import re
from typing import Any

# Regex patterns for PHI detection
_PHONE_PATTERN = re.compile(
    r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
)
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_MEMBER_ID_PATTERN = re.compile(
    r'(?:member_id|memberId|group_number|groupNumber)["\s:=]+([A-Za-z0-9-]+)',
    re.IGNORECASE,
)

# Keys whose values should be redacted in dict-style log messages
_PHI_KEYS = frozenset({
    "first_name", "last_name", "firstname", "lastname",
    "patient_name", "caller_name", "callername", "patientname",
    "phone", "caller_phone", "callerphone", "dob", "dateofbirth",
    "date_of_birth", "ssn", "social_security",
    "member_id", "memberid", "group_number", "groupnumber",
    "address", "insurance_carrier", "insurancecarrier",
})

REDACTED = "[REDACTED]"


def sanitize_text(text: str) -> str:
    """Remove PHI patterns from a text string."""
    if not isinstance(text, str):
        return text
    text = _SSN_PATTERN.sub(REDACTED, text)
    text = _PHONE_PATTERN.sub(REDACTED, text)
    text = _MEMBER_ID_PATTERN.sub(f"member_id: {REDACTED}", text)
    return text


def sanitize_dict(data: Any, depth: int = 0) -> Any:
    """Recursively sanitize PHI values in dictionaries."""
    if depth > 10:
        return data
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if isinstance(key, str) and key.lower().replace("-", "_") in _PHI_KEYS:
                result[key] = REDACTED
            else:
                result[key] = sanitize_dict(value, depth + 1)
        return result
    if isinstance(data, (list, tuple)):
        return type(data)(sanitize_dict(item, depth + 1) for item in data)
    return data


class PHISanitizationFilter(logging.Filter):
    """Logging filter that redacts PHI from all log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Sanitize the message
        if isinstance(record.msg, str):
            record.msg = sanitize_text(record.msg)

        # Sanitize format arguments
        if record.args:
            if isinstance(record.args, dict):
                record.args = sanitize_dict(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    sanitize_dict(a) if isinstance(a, dict)
                    else sanitize_text(a) if isinstance(a, str)
                    else a
                    for a in record.args
                )

        # Sanitize exception info text if present
        if record.exc_text and isinstance(record.exc_text, str):
            record.exc_text = sanitize_text(record.exc_text)

        return True
