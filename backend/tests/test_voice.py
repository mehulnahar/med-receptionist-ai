"""
Tests for the Voice AI modules.

Covers:
  - app.voice.triage   (keyword-based emergency detection)
  - app.voice.router   (model-tier classification: Haiku / Sonnet / Emergency)

All tests run without a real database connection or LLM calls.
"""

import time

import pytest

from app.voice.router import ModelTier, classify_query
from app.voice.triage import TriageResult, UrgencyLevel, detect_urgency


# ===================================================================
# Triage Tests
# ===================================================================


class TestDetectUrgency:
    """Tests for detect_urgency — keyword-based emergency triage."""

    # -- Emergency level --------------------------------------------------

    def test_detect_urgency_emergency_chest_pain(self):
        result = detect_urgency("I'm having chest pain")
        assert result.level == UrgencyLevel.EMERGENCY
        assert result.matched_keyword is not None
        assert "chest" in result.matched_keyword

    def test_detect_urgency_emergency_911(self):
        result = detect_urgency("please call 911 right now")
        assert result.level == UrgencyLevel.EMERGENCY
        assert "911" in result.matched_keyword

    def test_detect_urgency_emergency_cant_breathe(self):
        result = detect_urgency("I can't breathe")
        assert result.level == UrgencyLevel.EMERGENCY

    def test_detect_urgency_emergency_stroke(self):
        result = detect_urgency("I think I'm having a stroke")
        assert result.level == UrgencyLevel.EMERGENCY

    def test_detect_urgency_emergency_overdose(self):
        result = detect_urgency("my son took an overdose")
        assert result.level == UrgencyLevel.EMERGENCY

    def test_detect_urgency_emergency_suicidal(self):
        result = detect_urgency("I am feeling suicidal")
        assert result.level == UrgencyLevel.EMERGENCY

    # -- High priority ----------------------------------------------------

    def test_detect_urgency_high_very_sick(self):
        result = detect_urgency("I'm very sick and need help")
        assert result.level == UrgencyLevel.HIGH

    def test_detect_urgency_high_getting_worse(self):
        result = detect_urgency("my symptoms are getting worse")
        assert result.level == UrgencyLevel.HIGH

    def test_detect_urgency_high_child_sick(self):
        result = detect_urgency("my child is very sick")
        assert result.level == UrgencyLevel.HIGH

    # -- Normal level -----------------------------------------------------

    def test_detect_urgency_normal(self):
        result = detect_urgency("I'd like to book an appointment")
        assert result.level == UrgencyLevel.NORMAL
        assert result.matched_keyword is None

    def test_detect_urgency_normal_hours(self):
        result = detect_urgency("what are your office hours?")
        assert result.level == UrgencyLevel.NORMAL

    # -- Edge cases -------------------------------------------------------

    def test_detect_urgency_empty(self):
        result = detect_urgency("")
        assert result.level == UrgencyLevel.NORMAL
        assert result.matched_keyword is None

    def test_detect_urgency_whitespace_only(self):
        result = detect_urgency("   ")
        assert result.level == UrgencyLevel.NORMAL

    def test_detect_urgency_case_insensitive(self):
        result = detect_urgency("I HAVE CHEST PAIN")
        assert result.level == UrgencyLevel.EMERGENCY

    def test_detect_urgency_mixed_case(self):
        result = detect_urgency("Chest Pain is really bad")
        assert result.level == UrgencyLevel.EMERGENCY

    # -- Language parameter -----------------------------------------------

    def test_detect_urgency_spanish_language_param(self):
        """Emergency keywords are in English; passing language='es' should
        still detect them because the regex runs on the raw transcript."""
        result = detect_urgency("I have chest pain", language="es")
        assert result.level == UrgencyLevel.EMERGENCY

    def test_detect_urgency_spanish_message(self):
        """When language='es', the message_to_caller should be in Spanish."""
        result = detect_urgency("chest pain", language="es")
        assert result.level == UrgencyLevel.EMERGENCY
        assert "911" in result.message_to_caller
        # Spanish message contains "emergencia" or similar
        assert "emergencia" in result.message_to_caller.lower()

    # -- TriageResult structure -------------------------------------------

    def test_detect_urgency_result_structure(self):
        result = detect_urgency("chest pain")
        assert isinstance(result, TriageResult)
        assert isinstance(result.level, UrgencyLevel)
        assert isinstance(result.detection_time_ms, float)
        assert result.recommended_action == "immediate_transfer"

    # -- Performance ------------------------------------------------------

    def test_detect_urgency_performance(self):
        """Detection should complete in under 100 ms."""
        start = time.monotonic()
        result = detect_urgency("I am having severe chest pain and difficulty breathing")
        elapsed_ms = (time.monotonic() - start) * 1000
        assert elapsed_ms < 100, f"Triage took {elapsed_ms:.1f}ms, must be < 100ms"
        # Also check the internal timing
        assert result.detection_time_ms < 100

    def test_detect_urgency_performance_batch(self):
        """Run 100 detections; average should be well under 100 ms each."""
        transcripts = [
            "chest pain", "book appointment", "very sick",
            "what are your hours", "I can't breathe", "hello",
            "getting worse", "overdose", "cancel my appointment",
            "severe pain in my arm",
        ] * 10  # 100 transcripts

        start = time.monotonic()
        for t in transcripts:
            detect_urgency(t)
        total_ms = (time.monotonic() - start) * 1000
        avg_ms = total_ms / len(transcripts)
        assert avg_ms < 10, f"Average triage took {avg_ms:.2f}ms, should be < 10ms"


# ===================================================================
# Router Tests
# ===================================================================


class TestClassifyQuery:
    """Tests for classify_query — model tier routing."""

    # -- Emergency --------------------------------------------------------

    def test_classify_query_emergency(self):
        tier = classify_query("I'm having chest pain")
        assert tier == ModelTier.EMERGENCY

    def test_classify_query_emergency_911(self):
        tier = classify_query("call 911")
        assert tier == ModelTier.EMERGENCY

    # -- Sonnet (complex queries) -----------------------------------------

    def test_classify_query_sonnet_insurance(self):
        tier = classify_query("I need to verify my insurance coverage")
        assert tier == ModelTier.SONNET

    def test_classify_query_sonnet_complex(self):
        tier = classify_query(
            "I had a workers comp accident and need to see a specialist"
        )
        assert tier == ModelTier.SONNET

    def test_classify_query_sonnet_billing(self):
        tier = classify_query("I have a question about my billing statement")
        assert tier == ModelTier.SONNET

    def test_classify_query_sonnet_new_patient(self):
        tier = classify_query("I'm a new patient and want to register")
        assert tier == ModelTier.SONNET

    def test_classify_query_sonnet_referral(self):
        tier = classify_query("I need a referral to a specialist")
        assert tier == ModelTier.SONNET

    def test_classify_query_sonnet_high_priority_triage(self):
        """High-priority triage keywords (e.g. 'very sick') route to Sonnet
        because they need nuanced handling."""
        tier = classify_query("I am very sick and need help")
        assert tier == ModelTier.SONNET

    def test_classify_query_long_text_sonnet(self):
        """A query with > 20 words that doesn't match any specific pattern
        should default to Sonnet."""
        long_query = (
            "I am calling because I would like to understand what options "
            "are available for me regarding my ongoing treatment plan and "
            "whether there are any alternative approaches that we could discuss"
        )
        word_count = len(long_query.split())
        assert word_count > 20, f"Test query has only {word_count} words"
        tier = classify_query(long_query)
        assert tier == ModelTier.SONNET

    # -- Haiku (simple queries) -------------------------------------------

    def test_classify_query_haiku_hours(self):
        tier = classify_query("what are your hours")
        assert tier == ModelTier.HAIKU

    def test_classify_query_haiku_greeting(self):
        tier = classify_query("hello")
        assert tier == ModelTier.HAIKU

    def test_classify_query_haiku_address(self):
        tier = classify_query("where is your office located")
        assert tier == ModelTier.HAIKU

    def test_classify_query_haiku_thanks(self):
        tier = classify_query("thank you, goodbye")
        assert tier == ModelTier.HAIKU

    def test_classify_query_haiku_confirm(self):
        tier = classify_query("yes, that's correct")
        assert tier == ModelTier.HAIKU

    # -- Edge cases -------------------------------------------------------

    def test_classify_query_empty(self):
        tier = classify_query("")
        assert tier == ModelTier.HAIKU

    def test_classify_query_none_like_empty(self):
        tier = classify_query("   ")
        assert tier == ModelTier.HAIKU

    def test_classify_query_short_unclassified(self):
        """A short query with no pattern match defaults to Haiku."""
        tier = classify_query("banana smoothie recipe")
        assert tier == ModelTier.HAIKU
