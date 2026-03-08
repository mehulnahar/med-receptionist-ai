"""
Tests for Configurable Settings (Phase 1: CONF-05, CONF-06, CONF-07).

Tests schema validation for new PracticeConfig fields:
- transfer_message
- fallback_phone_number
- reminder_template_24h / reminder_template_2h
"""

import pytest
from app.schemas.practice_config import PracticeConfigUpdate, PracticeConfigResponse
from pydantic import ValidationError


class TestTransferMessageValidation:
    """CONF-07: Invalid transfer_message values rejected."""

    def test_valid_transfer_message(self):
        """CONF-06: Valid transfer message is accepted."""
        update = PracticeConfigUpdate(transfer_message="Transferring you now, please hold.")
        assert update.transfer_message == "Transferring you now, please hold."

    def test_empty_transfer_message_rejected(self):
        """CONF-07: Empty string transfer_message is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PracticeConfigUpdate(transfer_message="")
        assert "empty" in str(exc_info.value).lower()

    def test_whitespace_transfer_message_rejected(self):
        """CONF-07: Whitespace-only transfer_message is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PracticeConfigUpdate(transfer_message="   ")
        assert "empty" in str(exc_info.value).lower()

    def test_none_transfer_message_allowed(self):
        """None (unset) transfer_message passes -- it means 'don't update this field'."""
        update = PracticeConfigUpdate(transfer_message=None)
        assert update.transfer_message is None


class TestFallbackPhoneValidation:
    """CONF-04, CONF-07: Fallback phone number validation."""

    def test_valid_e164_phone(self):
        """CONF-06: Valid E.164 phone accepted."""
        update = PracticeConfigUpdate(fallback_phone_number="+12125551234")
        assert update.fallback_phone_number == "+12125551234"

    def test_invalid_phone_rejected(self):
        """CONF-07: Non-E.164 phone format rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PracticeConfigUpdate(fallback_phone_number="5551234")
        assert "E.164" in str(exc_info.value)

    def test_phone_without_plus_rejected(self):
        """CONF-07: Phone without + prefix rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PracticeConfigUpdate(fallback_phone_number="12125551234")
        assert "E.164" in str(exc_info.value)

    def test_none_fallback_phone_allowed(self):
        """None (unset) is valid -- no fallback configured."""
        update = PracticeConfigUpdate(fallback_phone_number=None)
        assert update.fallback_phone_number is None


class TestReminderTemplateValidation:
    """CONF-02, CONF-07: Reminder template validation."""

    def test_valid_reminder_template(self):
        """CONF-06: Valid template with all required placeholders accepted."""
        template = {
            "en": "Hi {patient_name}, appointment at {practice_name} on {date} at {time}.",
            "es": "Hola {patient_name}, cita en {practice_name} el {date} a las {time}."
        }
        update = PracticeConfigUpdate(reminder_template_24h=template)
        assert update.reminder_template_24h == template

    def test_template_missing_en_key_rejected(self):
        """CONF-07: Template without 'en' key is rejected."""
        template = {
            "es": "Hola {patient_name}, cita en {practice_name} el {date} a las {time}."
        }
        with pytest.raises(ValidationError) as exc_info:
            PracticeConfigUpdate(reminder_template_24h=template)
        assert "en" in str(exc_info.value).lower()

    def test_template_missing_placeholders_rejected(self):
        """CONF-07: Template missing required placeholders is rejected."""
        template = {
            "en": "You have an appointment tomorrow."  # Missing {patient_name}, {date}, {time}
        }
        with pytest.raises(ValidationError) as exc_info:
            PracticeConfigUpdate(reminder_template_24h=template)
        assert "patient_name" in str(exc_info.value) or "placeholder" in str(exc_info.value).lower()

    def test_empty_dict_template_allowed(self):
        """Empty dict means 'use defaults' -- should be accepted."""
        update = PracticeConfigUpdate(reminder_template_24h={})
        assert update.reminder_template_24h == {}

    def test_none_template_allowed(self):
        """None means 'don't update' -- should be accepted."""
        update = PracticeConfigUpdate(reminder_template_24h=None)
        assert update.reminder_template_24h is None

    def test_2h_template_validation(self):
        """CONF-06: 2-hour template also validates correctly."""
        template = {
            "en": "Hi {patient_name}, your appointment at {practice_name} is at {time} on {date}."
        }
        update = PracticeConfigUpdate(reminder_template_2h=template)
        assert update.reminder_template_2h == template


class TestExistingValidation:
    """CONF-05: Verify existing phone validation still works."""

    def test_transfer_number_e164_valid(self):
        update = PracticeConfigUpdate(transfer_number="+12125551234")
        assert update.transfer_number == "+12125551234"

    def test_transfer_number_invalid_rejected(self):
        with pytest.raises(ValidationError):
            PracticeConfigUpdate(transfer_number="bad-number")

    def test_masked_secret_rejected(self):
        """Masked secrets (echoed from frontend) are rejected."""
        with pytest.raises(ValidationError):
            PracticeConfigUpdate(vapi_api_key="****abcd1234")
