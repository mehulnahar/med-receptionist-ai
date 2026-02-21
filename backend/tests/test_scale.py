"""
Tests for the Phase 5 (Scale & Intelligence) modules.

Covers:
  - app.scale.concurrent_calls  (ConcurrentCallManager — slot acquisition, release, stats)
  - app.scale.load_monitor      (PerformanceMonitor — latency tracking, alerts, health score)
  - app.scale.survey_service     (survey token lifecycle, NPS calculation, config merging)
  - app.scale.waitlist_notifier  (cancellation notifications, response handling, expiry)

All tests run without a real database connection or external services.
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset ConcurrentCallManager and PerformanceMonitor singletons
    before and after every test so state never leaks."""
    from app.scale.concurrent_calls import ConcurrentCallManager
    from app.scale.load_monitor import PerformanceMonitor

    ConcurrentCallManager.reset()
    PerformanceMonitor.reset()
    yield
    ConcurrentCallManager.reset()
    PerformanceMonitor.reset()


@pytest.fixture()
def _survey_env(monkeypatch):
    """Set environment variables required by the survey token helpers
    and clear the settings cache so they take effect."""
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-surveys")
    monkeypatch.setenv("APP_URL", "http://localhost:8000")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "")
    from app.config import clear_settings_cache
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.fixture()
def mock_db():
    """Create a mock AsyncSession with execute, commit, and rollback."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _make_row(**kwargs):
    """Helper: create a MagicMock that acts like a SQLAlchemy Row with
    named attributes accessible via dot notation."""
    row = MagicMock()
    for key, value in kwargs.items():
        setattr(row, key, value)
    return row


# ===================================================================
# ConcurrentCallManager Tests
# ===================================================================


class TestConcurrentCallManagerSingleton:
    """Tests for singleton pattern and reset behaviour."""

    def test_get_instance_returns_same_object(self):
        from app.scale.concurrent_calls import ConcurrentCallManager

        a = ConcurrentCallManager.get_instance(max_concurrent=5)
        b = ConcurrentCallManager.get_instance(max_concurrent=5)
        assert a is b

    def test_reset_clears_singleton(self):
        from app.scale.concurrent_calls import ConcurrentCallManager

        a = ConcurrentCallManager.get_instance(max_concurrent=5)
        ConcurrentCallManager.reset()
        b = ConcurrentCallManager.get_instance(max_concurrent=5)
        assert a is not b


class TestConcurrentCallManagerAcquireRelease:
    """Tests for acquiring and releasing call slots."""

    async def test_acquire_slot_returns_true(self):
        from app.scale.concurrent_calls import ConcurrentCallManager

        mgr = ConcurrentCallManager.get_instance(max_concurrent=2)
        result = await mgr.acquire_slot("call-1", "practice-1", "+15551234567")
        assert result is True

    async def test_release_slot_succeeds(self):
        from app.scale.concurrent_calls import ConcurrentCallManager

        mgr = ConcurrentCallManager.get_instance(max_concurrent=2)
        await mgr.acquire_slot("call-1", "practice-1", "+15551234567")
        await mgr.release_slot("call-1")

        active = await mgr.get_active_calls()
        assert len(active) == 0

    async def test_release_unknown_call_id_does_not_crash(self):
        """Releasing a call_id that was never acquired should not raise."""
        from app.scale.concurrent_calls import ConcurrentCallManager

        mgr = ConcurrentCallManager.get_instance(max_concurrent=2)
        # Should complete without error
        await mgr.release_slot("nonexistent-call-id")

    async def test_active_calls_tracked_correctly(self):
        from app.scale.concurrent_calls import ConcurrentCallManager

        mgr = ConcurrentCallManager.get_instance(max_concurrent=5)
        await mgr.acquire_slot("call-A", "p1", "+1111")
        await mgr.acquire_slot("call-B", "p2", "+2222")

        active = await mgr.get_active_calls()
        assert len(active) == 2

        call_ids = {c["call_id"] for c in active}
        assert call_ids == {"call-A", "call-B"}

        # Each entry should contain expected keys
        for c in active:
            assert "practice_id" in c
            assert "caller_phone" in c
            assert "duration_seconds" in c
            assert "status" in c

    async def test_active_calls_after_release(self):
        from app.scale.concurrent_calls import ConcurrentCallManager

        mgr = ConcurrentCallManager.get_instance(max_concurrent=5)
        await mgr.acquire_slot("call-A", "p1", "+1111")
        await mgr.acquire_slot("call-B", "p2", "+2222")
        await mgr.release_slot("call-A")

        active = await mgr.get_active_calls()
        assert len(active) == 1
        assert active[0]["call_id"] == "call-B"


class TestConcurrentCallManagerCapacity:
    """Tests for capacity enforcement — reject when at max_concurrent."""

    async def test_reject_when_at_capacity(self):
        from app.scale.concurrent_calls import ConcurrentCallManager

        mgr = ConcurrentCallManager.get_instance(max_concurrent=2)
        assert await mgr.acquire_slot("c1", "p1", "+111") is True
        assert await mgr.acquire_slot("c2", "p1", "+222") is True
        # Third call should be rejected
        assert await mgr.acquire_slot("c3", "p1", "+333") is False

    async def test_rejected_count_increments(self):
        from app.scale.concurrent_calls import ConcurrentCallManager

        mgr = ConcurrentCallManager.get_instance(max_concurrent=1)
        await mgr.acquire_slot("c1", "p1", "+111")
        await mgr.acquire_slot("c2", "p1", "+222")  # rejected
        await mgr.acquire_slot("c3", "p1", "+333")  # rejected

        stats = await mgr.get_stats()
        assert stats["rejected_count"] == 2

    async def test_slot_freed_after_release_allows_new_acquire(self):
        from app.scale.concurrent_calls import ConcurrentCallManager

        mgr = ConcurrentCallManager.get_instance(max_concurrent=1)
        await mgr.acquire_slot("c1", "p1", "+111")
        await mgr.release_slot("c1")
        result = await mgr.acquire_slot("c2", "p1", "+222")
        assert result is True


class TestConcurrentCallManagerStats:
    """Tests for get_stats — peak count, utilization, avg duration."""

    async def test_stats_initial_values(self):
        from app.scale.concurrent_calls import ConcurrentCallManager

        mgr = ConcurrentCallManager.get_instance(max_concurrent=5)
        stats = await mgr.get_stats()

        assert stats["active_count"] == 0
        assert stats["max_concurrent"] == 5
        assert stats["peak_count"] == 0
        assert stats["total_handled"] == 0
        assert stats["rejected_count"] == 0
        assert stats["avg_duration_seconds"] == 0.0
        assert stats["utilization_pct"] == 0.0

    async def test_peak_count_tracking(self):
        from app.scale.concurrent_calls import ConcurrentCallManager

        mgr = ConcurrentCallManager.get_instance(max_concurrent=5)
        await mgr.acquire_slot("c1", "p1", "+111")
        await mgr.acquire_slot("c2", "p1", "+222")
        await mgr.acquire_slot("c3", "p1", "+333")
        # Peak is 3
        await mgr.release_slot("c1")
        await mgr.release_slot("c2")
        # Currently 1 active, but peak should still be 3

        stats = await mgr.get_stats()
        assert stats["peak_count"] == 3
        assert stats["active_count"] == 1

    async def test_total_handled_count(self):
        from app.scale.concurrent_calls import ConcurrentCallManager

        mgr = ConcurrentCallManager.get_instance(max_concurrent=5)
        await mgr.acquire_slot("c1", "p1", "+111")
        await mgr.acquire_slot("c2", "p1", "+222")

        stats = await mgr.get_stats()
        assert stats["total_handled"] == 2

    async def test_utilization_pct(self):
        from app.scale.concurrent_calls import ConcurrentCallManager

        mgr = ConcurrentCallManager.get_instance(max_concurrent=4)
        await mgr.acquire_slot("c1", "p1", "+111")
        await mgr.acquire_slot("c2", "p1", "+222")

        stats = await mgr.get_stats()
        # 2 active / 4 max = 50%
        assert stats["utilization_pct"] == 50.0

    async def test_avg_duration_seconds(self):
        """avg_duration_seconds should be calculated from completed calls only."""
        from app.scale.concurrent_calls import ConcurrentCallManager

        mgr = ConcurrentCallManager.get_instance(max_concurrent=5)
        await mgr.acquire_slot("c1", "p1", "+111")
        # Simulate a short call
        await asyncio.sleep(0.05)
        await mgr.release_slot("c1")

        stats = await mgr.get_stats()
        # Should be >= 0.0 (at least ~50ms)
        assert stats["avg_duration_seconds"] > 0.0
        assert stats["total_handled"] == 1

    async def test_stats_keys_present(self):
        from app.scale.concurrent_calls import ConcurrentCallManager

        mgr = ConcurrentCallManager.get_instance(max_concurrent=5)
        stats = await mgr.get_stats()

        expected_keys = {
            "active_count",
            "max_concurrent",
            "peak_count",
            "total_handled",
            "rejected_count",
            "avg_duration_seconds",
            "utilization_pct",
        }
        assert set(stats.keys()) == expected_keys


# ===================================================================
# PerformanceMonitor Tests
# ===================================================================


class TestPerformanceMonitorSingleton:
    """Tests for singleton pattern and reset."""

    def test_get_instance_returns_same_object(self):
        from app.scale.load_monitor import PerformanceMonitor

        a = PerformanceMonitor.get_instance()
        b = PerformanceMonitor.get_instance()
        assert a is b

    def test_reset_clears_singleton(self):
        from app.scale.load_monitor import PerformanceMonitor

        a = PerformanceMonitor.get_instance()
        PerformanceMonitor.reset()
        b = PerformanceMonitor.get_instance()
        assert a is not b


class TestPerformanceMonitorLatency:
    """Tests for recording and querying latency percentiles."""

    def test_empty_phase_returns_zeros(self):
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        stats = mon.get_latency_percentiles("stt")

        assert stats["p50"] == 0
        assert stats["p95"] == 0
        assert stats["p99"] == 0
        assert stats["avg"] == 0
        assert stats["count"] == 0

    def test_record_and_retrieve_single_latency(self):
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        mon.record_call_latency("call-1", "stt", 150.0)

        stats = mon.get_latency_percentiles("stt")
        assert stats["count"] == 1
        assert stats["avg"] == 150.0
        assert stats["p50"] == 150.0

    def test_record_and_retrieve_multiple_latencies(self):
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        values = [100.0, 200.0, 300.0, 400.0, 500.0]
        for i, v in enumerate(values):
            mon.record_call_latency(f"call-{i}", "llm", v)

        stats = mon.get_latency_percentiles("llm")
        assert stats["count"] == 5
        assert stats["avg"] == 300.0
        # p50 of [100,200,300,400,500] is values[2]=300
        assert stats["p50"] == 300.0

    def test_different_phases_are_independent(self):
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        mon.record_call_latency("c1", "stt", 100.0)
        mon.record_call_latency("c1", "llm", 400.0)
        mon.record_call_latency("c1", "tts", 200.0)

        stt = mon.get_latency_percentiles("stt")
        llm = mon.get_latency_percentiles("llm")
        tts = mon.get_latency_percentiles("tts")

        assert stt["avg"] == 100.0
        assert llm["avg"] == 400.0
        assert tts["avg"] == 200.0

    def test_api_latency_recording(self):
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        mon.record_api_latency("/api/v1/appointments", "GET", 250.0, 200)
        mon.record_api_latency("/api/v1/appointments", "POST", 350.0, 201)

        stats = mon.get_latency_percentiles("api_p95")
        assert stats["count"] == 2
        assert stats["avg"] == 300.0

    def test_percentiles_respect_window(self):
        """Records outside the time window should be excluded."""
        from app.scale.load_monitor import PerformanceMonitor, LatencyRecord
        from collections import deque

        mon = PerformanceMonitor.get_instance()
        # Inject a record with a timestamp far in the past (10 minutes ago)
        old_record = LatencyRecord(
            timestamp=time.time() - 600,
            duration_ms=9999.0,
        )
        mon._call_latencies["stt"] = deque(maxlen=mon.MAX_RECORDS)
        mon._call_latencies["stt"].append(old_record)

        # Record a fresh one
        mon.record_call_latency("c1", "stt", 100.0)

        stats = mon.get_latency_percentiles("stt", window_minutes=5)
        # The old record should be excluded
        assert stats["count"] == 1
        assert stats["avg"] == 100.0


class TestPerformanceMonitorAlerts:
    """Tests for alert triggering based on threshold breaches."""

    def test_no_alerts_when_below_thresholds(self):
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        # Record values well below all thresholds
        mon.record_call_latency("c1", "stt", 50.0)
        mon.record_call_latency("c1", "llm", 100.0)
        mon.record_call_latency("c1", "tts", 50.0)
        mon.record_call_latency("c1", "total", 200.0)

        alerts = mon.check_alerts()
        assert len(alerts) == 0

    def test_alert_triggers_when_p95_exceeds_threshold(self):
        """When total p95 > 1000ms, a critical alert should fire."""
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        # All values are above the 1000ms threshold for 'total'
        for i in range(10):
            mon.record_call_latency(f"c{i}", "total", 1500.0)

        alerts = mon.check_alerts()
        total_alerts = [a for a in alerts if a["metric"] == "total"]
        assert len(total_alerts) == 1
        assert total_alerts[0]["severity"] == "critical"
        assert total_alerts[0]["current_p95_ms"] > 1000.0

    def test_warning_alert_for_stt(self):
        """When STT p95 > 300ms, a warning alert should fire."""
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        for i in range(10):
            mon.record_call_latency(f"c{i}", "stt", 400.0)

        alerts = mon.check_alerts()
        stt_alerts = [a for a in alerts if a["metric"] == "stt"]
        assert len(stt_alerts) == 1
        assert stt_alerts[0]["severity"] == "warning"

    def test_alert_contains_required_fields(self):
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        for i in range(10):
            mon.record_call_latency(f"c{i}", "total", 2000.0)

        alerts = mon.check_alerts()
        assert len(alerts) >= 1
        alert = alerts[0]

        expected_keys = {
            "name",
            "metric",
            "severity",
            "threshold_ms",
            "current_p95_ms",
            "current_avg_ms",
            "sample_count",
            "window_minutes",
        }
        assert set(alert.keys()) == expected_keys

    def test_no_alerts_with_no_data(self):
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        alerts = mon.check_alerts()
        assert alerts == []


class TestPerformanceMonitorHealthScore:
    """Tests for health_score — decrements based on alerts."""

    def test_health_score_100_when_no_alerts(self):
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        assert mon.health_score() == 100

    def test_health_score_decrements_25_for_critical(self):
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        # Trigger ONE critical alert (total > 1000ms)
        for i in range(10):
            mon.record_call_latency(f"c{i}", "total", 1500.0)

        score = mon.health_score()
        assert score == 75

    def test_health_score_decrements_10_for_warning(self):
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        # Trigger ONE warning alert (stt > 300ms) but keep others below
        for i in range(10):
            mon.record_call_latency(f"c{i}", "stt", 400.0)

        score = mon.health_score()
        assert score == 90

    def test_health_score_floors_at_zero(self):
        """Score should never go below 0 even with many alerts."""
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        # Trigger multiple critical and warning alerts
        for i in range(10):
            mon.record_call_latency(f"c{i}", "total", 5000.0)
            mon.record_call_latency(f"c{i}", "stt", 1000.0)
            mon.record_call_latency(f"c{i}", "llm", 1000.0)
            mon.record_call_latency(f"c{i}", "tts", 1000.0)
            mon.record_api_latency(f"/api/{i}", "GET", 5000.0, 200)

        score = mon.health_score()
        assert score >= 0

    def test_health_score_multiple_warnings(self):
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        # Trigger all 3 warning-level alerts (stt, llm, tts)
        for i in range(10):
            mon.record_call_latency(f"c{i}", "stt", 400.0)   # > 300 warning
            mon.record_call_latency(f"c{i}", "llm", 600.0)   # > 500 warning
            mon.record_call_latency(f"c{i}", "tts", 400.0)   # > 300 warning

        score = mon.health_score()
        # 100 - (3 * 10) = 70
        assert score == 70


class TestPerformanceMonitorExportMetrics:
    """Tests for export_metrics format and content."""

    def test_export_metrics_has_required_keys(self):
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        metrics = mon.export_metrics()

        assert "timestamp" in metrics
        assert "voice_pipeline" in metrics
        assert "api" in metrics
        assert "health_score" in metrics
        assert "alerts" in metrics

    def test_export_metrics_voice_pipeline_phases(self):
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        metrics = mon.export_metrics()

        for phase in ("stt", "llm", "tts", "total"):
            assert phase in metrics["voice_pipeline"]
            assert "p50" in metrics["voice_pipeline"][phase]
            assert "p95" in metrics["voice_pipeline"][phase]
            assert "count" in metrics["voice_pipeline"][phase]

    def test_export_metrics_api_error_rate(self):
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        # 2 successful + 1 server error = 33.33% error rate
        mon.record_api_latency("/api/test", "GET", 100.0, 200)
        mon.record_api_latency("/api/test", "GET", 100.0, 200)
        mon.record_api_latency("/api/test", "POST", 100.0, 500)

        metrics = mon.export_metrics()
        assert metrics["api"]["total_requests"] == 3
        assert metrics["api"]["error_rate_pct"] == pytest.approx(33.33, abs=0.01)

    def test_export_metrics_api_no_requests(self):
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        metrics = mon.export_metrics()

        assert metrics["api"]["error_rate_pct"] == 0
        assert metrics["api"]["total_requests"] == 0

    def test_export_metrics_api_all_success(self):
        from app.scale.load_monitor import PerformanceMonitor

        mon = PerformanceMonitor.get_instance()
        for i in range(5):
            mon.record_api_latency("/api/test", "GET", 100.0, 200)

        metrics = mon.export_metrics()
        assert metrics["api"]["error_rate_pct"] == 0
        assert metrics["api"]["total_requests"] == 5


# ===================================================================
# Survey Service Tests
# ===================================================================


class TestSurveyConfig:
    """Tests for _get_survey_config — merging practice overrides with defaults."""

    def test_defaults_when_no_survey_key(self):
        from app.scale.survey_service import _get_survey_config, DEFAULT_SURVEY_CONFIG

        result = _get_survey_config({})
        assert result == DEFAULT_SURVEY_CONFIG

    def test_defaults_when_empty_survey(self):
        from app.scale.survey_service import _get_survey_config, DEFAULT_SURVEY_CONFIG

        result = _get_survey_config({"survey": {}})
        assert result == DEFAULT_SURVEY_CONFIG

    def test_override_specific_field(self):
        from app.scale.survey_service import _get_survey_config

        practice_config = {
            "survey": {
                "delay_hours": 4,
                "min_rating_for_review": 5,
            }
        }
        result = _get_survey_config(practice_config)
        assert result["delay_hours"] == 4
        assert result["min_rating_for_review"] == 5
        # Defaults should still be present for non-overridden fields
        assert result["enabled"] is True
        assert result["include_google_review"] is True

    def test_override_enabled_false(self):
        from app.scale.survey_service import _get_survey_config

        result = _get_survey_config({"survey": {"enabled": False}})
        assert result["enabled"] is False

    def test_custom_google_review_url(self):
        from app.scale.survey_service import _get_survey_config

        result = _get_survey_config(
            {"survey": {"google_review_url": "https://g.page/review/myoffice"}}
        )
        assert result["google_review_url"] == "https://g.page/review/myoffice"


class TestSurveyTokenLifecycle:
    """Tests for _create_survey_token and _decode_survey_token roundtrip."""

    @pytest.mark.usefixtures("_survey_env")
    def test_create_and_decode_roundtrip(self):
        from app.scale.survey_service import _create_survey_token, _decode_survey_token

        appt_id = str(uuid4())
        practice_id = str(uuid4())

        token = _create_survey_token(appt_id, practice_id)
        assert isinstance(token, str)
        assert len(token) > 0

        decoded = _decode_survey_token(token)
        assert decoded is not None
        assert decoded["type"] == "survey"
        assert decoded["appointment_id"] == appt_id
        assert decoded["practice_id"] == practice_id

    @pytest.mark.usefixtures("_survey_env")
    def test_expired_token_returns_none(self):
        """A token whose exp is in the past should decode to None."""
        import jwt as pyjwt

        appt_id = str(uuid4())
        practice_id = str(uuid4())

        payload = {
            "type": "survey",
            "appointment_id": appt_id,
            "practice_id": practice_id,
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        token = pyjwt.encode(payload, "test-secret-for-surveys", algorithm="HS256")

        from app.scale.survey_service import _decode_survey_token
        result = _decode_survey_token(token)
        assert result is None

    @pytest.mark.usefixtures("_survey_env")
    def test_invalid_token_returns_none(self):
        from app.scale.survey_service import _decode_survey_token

        result = _decode_survey_token("not.a.valid.jwt.token")
        assert result is None

    @pytest.mark.usefixtures("_survey_env")
    def test_token_with_wrong_secret_returns_none(self):
        """A token signed with a different secret should fail decoding."""
        import jwt as pyjwt

        payload = {
            "type": "survey",
            "appointment_id": "appt-1",
            "practice_id": "practice-1",
            "exp": datetime.now(timezone.utc) + timedelta(hours=72),
        }
        token = pyjwt.encode(payload, "wrong-secret", algorithm="HS256")

        from app.scale.survey_service import _decode_survey_token
        result = _decode_survey_token(token)
        assert result is None


class TestProcessSurveyResponse:
    """Tests for process_survey_response — rating clamping and token validation."""

    @pytest.mark.usefixtures("_survey_env")
    async def test_invalid_token_returns_error(self, mock_db):
        from app.scale.survey_service import process_survey_response

        result = await process_survey_response(mock_db, "bad-token", 5, "Great!")
        assert "error" in result

    @pytest.mark.usefixtures("_survey_env")
    async def test_rating_clamped_to_1_when_zero(self, mock_db):
        """Rating 0 should be clamped up to 1."""
        from app.scale.survey_service import (
            _create_survey_token,
            process_survey_response,
        )

        token = _create_survey_token("appt-1", "practice-1")

        # Mock the update query and config query
        mock_config_row = _make_row(config={"survey": {"include_google_review": False}})
        mock_config_result = MagicMock()
        mock_config_result.fetchone.return_value = mock_config_row
        mock_db.execute = AsyncMock(return_value=mock_config_result)

        result = await process_survey_response(mock_db, token, 0, "Bad experience")
        assert result["rating"] == 1

    @pytest.mark.usefixtures("_survey_env")
    async def test_rating_clamped_to_5_when_above(self, mock_db):
        """Rating 6 should be clamped down to 5."""
        from app.scale.survey_service import (
            _create_survey_token,
            process_survey_response,
        )

        token = _create_survey_token("appt-2", "practice-2")

        mock_config_row = _make_row(config={"survey": {"include_google_review": False}})
        mock_config_result = MagicMock()
        mock_config_result.fetchone.return_value = mock_config_row
        mock_db.execute = AsyncMock(return_value=mock_config_result)

        result = await process_survey_response(mock_db, token, 6, "Amazing!")
        assert result["rating"] == 5

    @pytest.mark.usefixtures("_survey_env")
    async def test_valid_rating_passes_through(self, mock_db):
        """A rating of 3 should be preserved as-is."""
        from app.scale.survey_service import (
            _create_survey_token,
            process_survey_response,
        )

        token = _create_survey_token("appt-3", "practice-3")

        mock_config_row = _make_row(config={"survey": {"include_google_review": False}})
        mock_config_result = MagicMock()
        mock_config_result.fetchone.return_value = mock_config_row
        mock_db.execute = AsyncMock(return_value=mock_config_result)

        result = await process_survey_response(mock_db, token, 3, "Okay visit")
        assert result["rating"] == 3


class TestSendPostVisitSurvey:
    """Tests for send_post_visit_survey — edge cases with mocked DB."""

    @pytest.mark.usefixtures("_survey_env")
    async def test_returns_none_when_appointment_not_found(self, mock_db):
        from app.scale.survey_service import send_post_visit_survey

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await send_post_visit_survey(mock_db, "nonexistent-appt")
        assert result is None

    @pytest.mark.usefixtures("_survey_env")
    async def test_returns_none_when_no_patient_phone(self, mock_db):
        from app.scale.survey_service import send_post_visit_survey

        row = _make_row(patient_phone=None)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await send_post_visit_survey(mock_db, "appt-1")
        assert result is None

    @pytest.mark.usefixtures("_survey_env")
    async def test_returns_none_when_survey_already_exists(self, mock_db):
        from app.scale.survey_service import send_post_visit_survey

        # First execute: appointment row found
        appt_row = _make_row(
            id=uuid4(),
            practice_id=uuid4(),
            patient_id=uuid4(),
            patient_first="Maria",
            patient_last="Garcia",
            patient_phone="+15551234567",
            preferred_language="en",
            provider_first="John",
            provider_last="Smith",
        )
        mock_appt_result = MagicMock()
        mock_appt_result.fetchone.return_value = appt_row

        # Second execute: existing survey found
        existing_survey_row = _make_row(id=uuid4())
        mock_survey_result = MagicMock()
        mock_survey_result.fetchone.return_value = existing_survey_row

        mock_db.execute = AsyncMock(
            side_effect=[mock_appt_result, mock_survey_result]
        )

        result = await send_post_visit_survey(mock_db, "appt-1")
        assert result is None


class TestGetSurveyStats:
    """Tests for get_survey_stats — NPS calculation."""

    @pytest.mark.usefixtures("_survey_env")
    async def test_nps_all_promoters(self, mock_db):
        """All 5-star ratings = NPS of 100."""
        from app.scale.survey_service import get_survey_stats

        row = _make_row(
            total_sent=10,
            total_responded=10,
            avg_rating=5.0,
            promoters=10,
            passives=0,
            detractors=0,
        )
        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        mock_db.execute = AsyncMock(return_value=mock_result)

        stats = await get_survey_stats(mock_db, "practice-1", "month")
        assert stats["nps_score"] == 100.0

    @pytest.mark.usefixtures("_survey_env")
    async def test_nps_all_detractors(self, mock_db):
        """All 1-star ratings = NPS of -100."""
        from app.scale.survey_service import get_survey_stats

        row = _make_row(
            total_sent=10,
            total_responded=10,
            avg_rating=1.0,
            promoters=0,
            passives=0,
            detractors=10,
        )
        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        mock_db.execute = AsyncMock(return_value=mock_result)

        stats = await get_survey_stats(mock_db, "practice-1", "month")
        assert stats["nps_score"] == -100.0

    @pytest.mark.usefixtures("_survey_env")
    async def test_nps_mixed_ratings(self, mock_db):
        """5 promoters, 3 passives, 2 detractors out of 10 = NPS 30."""
        from app.scale.survey_service import get_survey_stats

        row = _make_row(
            total_sent=10,
            total_responded=10,
            avg_rating=3.8,
            promoters=5,
            passives=3,
            detractors=2,
        )
        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        mock_db.execute = AsyncMock(return_value=mock_result)

        stats = await get_survey_stats(mock_db, "practice-1", "month")
        # NPS = (5 - 2) / 10 * 100 = 30.0
        assert stats["nps_score"] == 30.0

    @pytest.mark.usefixtures("_survey_env")
    async def test_no_responses_nps_zero(self, mock_db):
        from app.scale.survey_service import get_survey_stats

        row = _make_row(
            total_sent=10,
            total_responded=0,
            avg_rating=0,
            promoters=0,
            passives=0,
            detractors=0,
        )
        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        mock_db.execute = AsyncMock(return_value=mock_result)

        stats = await get_survey_stats(mock_db, "practice-1", "month")
        assert stats["nps_score"] == 0.0
        assert stats["response_rate"] == 0

    @pytest.mark.usefixtures("_survey_env")
    async def test_response_rate_calculation(self, mock_db):
        from app.scale.survey_service import get_survey_stats

        row = _make_row(
            total_sent=20,
            total_responded=15,
            avg_rating=4.2,
            promoters=10,
            passives=3,
            detractors=2,
        )
        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        mock_db.execute = AsyncMock(return_value=mock_result)

        stats = await get_survey_stats(mock_db, "practice-1", "month")
        assert stats["response_rate"] == 75.0
        assert stats["total_sent"] == 20
        assert stats["total_responded"] == 15

    @pytest.mark.usefixtures("_survey_env")
    async def test_stats_output_keys(self, mock_db):
        from app.scale.survey_service import get_survey_stats

        row = _make_row(
            total_sent=1,
            total_responded=1,
            avg_rating=5.0,
            promoters=1,
            passives=0,
            detractors=0,
        )
        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        mock_db.execute = AsyncMock(return_value=mock_result)

        stats = await get_survey_stats(mock_db, "practice-1", "month")
        expected_keys = {
            "total_sent",
            "total_responded",
            "avg_rating",
            "nps_score",
            "response_rate",
            "promoters",
            "passives",
            "detractors",
        }
        assert set(stats.keys()) == expected_keys


# ===================================================================
# Waitlist Notifier Tests
# ===================================================================


class TestOnAppointmentCancelled:
    """Tests for on_appointment_cancelled — notifying waitlisted patients."""

    async def test_returns_empty_when_appointment_not_found(self, mock_db):
        from app.scale.waitlist_notifier import on_appointment_cancelled

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await on_appointment_cancelled(mock_db, "nonexistent-appt")
        assert result == []

    async def test_returns_empty_when_no_matching_waitlist_entries(self, mock_db):
        from app.scale.waitlist_notifier import on_appointment_cancelled

        # First execute: appointment found
        appt_row = _make_row(
            id=uuid4(),
            practice_id=uuid4(),
            date=datetime(2025, 7, 1).date(),
            start_time=datetime(2025, 7, 1, 9, 0).time(),
            end_time=datetime(2025, 7, 1, 9, 30).time(),
            appointment_type_id=uuid4(),
            provider_id=uuid4(),
            provider_first="John",
            provider_last="Smith",
        )
        mock_appt_result = MagicMock()
        mock_appt_result.fetchone.return_value = appt_row

        # Second execute: no matching waitlist entries
        mock_waitlist_result = MagicMock()
        mock_waitlist_result.fetchall.return_value = []

        mock_db.execute = AsyncMock(
            side_effect=[mock_appt_result, mock_waitlist_result]
        )

        result = await on_appointment_cancelled(mock_db, "appt-1")
        assert result == []

    async def test_notifies_matching_waitlist_entries(self, mock_db):
        """When matching entries exist, should notify them and return details."""
        from app.scale.waitlist_notifier import on_appointment_cancelled

        # Use MagicMock for start_time/date so strftime with %-I (Linux-only)
        # doesn't fail on Windows; the mock just returns a string.
        mock_date = MagicMock()
        mock_date.strftime.return_value = "July 01"
        mock_start_time = MagicMock()
        mock_start_time.strftime.return_value = "9:00 AM"

        appt_row = _make_row(
            id=uuid4(),
            practice_id=uuid4(),
            date=mock_date,
            start_time=mock_start_time,
            end_time=datetime(2025, 7, 1, 9, 30).time(),
            appointment_type_id=uuid4(),
            provider_id=uuid4(),
            provider_first="John",
            provider_last="Smith",
        )
        mock_appt_result = MagicMock()
        mock_appt_result.fetchone.return_value = appt_row

        entry_1 = _make_row(
            id=uuid4(),
            patient_name="Maria Garcia",
            patient_phone="+15551111111",
            appointment_type_id=None,
            preferred_date_start=None,
            preferred_date_end=None,
            preferred_time_start=None,
            preferred_time_end=None,
        )
        entry_2 = _make_row(
            id=uuid4(),
            patient_name="Carlos Lopez",
            patient_phone="+15552222222",
            appointment_type_id=None,
            preferred_date_start=None,
            preferred_date_end=None,
            preferred_time_start=None,
            preferred_time_end=None,
        )
        mock_waitlist_result = MagicMock()
        mock_waitlist_result.fetchall.return_value = [entry_1, entry_2]

        # Subsequent execute calls are for the UPDATE statements
        mock_update_result = MagicMock()

        mock_db.execute = AsyncMock(
            side_effect=[mock_appt_result, mock_waitlist_result, mock_update_result, mock_update_result]
        )

        with patch(
            "app.scale.waitlist_notifier._send_waitlist_sms",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await on_appointment_cancelled(mock_db, "appt-1")

        assert len(result) == 2
        assert result[0]["patient_name"] == "Maria Garcia"
        assert result[1]["patient_name"] == "Carlos Lopez"
        assert result[0]["sms_sent"] is True
        mock_db.commit.assert_awaited_once()


class TestProcessWaitlistResponse:
    """Tests for process_waitlist_response — YES/SI/NO handling."""

    async def test_yes_response_books(self, mock_db):
        from app.scale.waitlist_notifier import process_waitlist_response

        entry = _make_row(
            id=uuid4(),
            practice_id=uuid4(),
            patient_name="Maria Garcia",
            patient_phone="+15551111111",
            appointment_type_id=None,
            notified_at=datetime.now(timezone.utc),
        )
        mock_result = MagicMock()
        mock_result.fetchone.return_value = entry
        mock_update_result = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[mock_result, mock_update_result, mock_update_result, mock_update_result]
        )

        with patch(
            "app.scale.waitlist_notifier._send_waitlist_sms",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await process_waitlist_response(mock_db, "+15551111111", "YES")

        assert result["status"] == "booked"
        assert result["patient_name"] == "Maria Garcia"

    async def test_si_response_books(self, mock_db):
        """Spanish 'SI' should be treated as an affirmative."""
        from app.scale.waitlist_notifier import process_waitlist_response

        entry = _make_row(
            id=uuid4(),
            practice_id=uuid4(),
            patient_name="Carlos Lopez",
            patient_phone="+15552222222",
            appointment_type_id=None,
            notified_at=datetime.now(timezone.utc),
        )
        mock_result = MagicMock()
        mock_result.fetchone.return_value = entry
        mock_update_result = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[mock_result, mock_update_result, mock_update_result, mock_update_result]
        )

        with patch(
            "app.scale.waitlist_notifier._send_waitlist_sms",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await process_waitlist_response(mock_db, "+15552222222", "SI")

        assert result["status"] == "booked"

    async def test_no_response_declines(self, mock_db):
        from app.scale.waitlist_notifier import process_waitlist_response

        entry = _make_row(
            id=uuid4(),
            practice_id=uuid4(),
            patient_name="Ana Martinez",
            patient_phone="+15553333333",
            appointment_type_id=None,
            notified_at=datetime.now(timezone.utc),
        )
        mock_result = MagicMock()
        mock_result.fetchone.return_value = entry
        mock_update_result = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[mock_result, mock_update_result]
        )

        result = await process_waitlist_response(mock_db, "+15553333333", "NO")
        assert result["status"] == "declined"
        assert result["patient_name"] == "Ana Martinez"

    async def test_no_active_notification(self, mock_db):
        from app.scale.waitlist_notifier import process_waitlist_response

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await process_waitlist_response(mock_db, "+15559999999", "YES")
        assert result["status"] == "no_active_notification"
        assert result["phone"] == "+15559999999"

    async def test_lowercase_yes_books(self, mock_db):
        """Case-insensitive: 'yes' should work like 'YES'."""
        from app.scale.waitlist_notifier import process_waitlist_response

        entry = _make_row(
            id=uuid4(),
            practice_id=uuid4(),
            patient_name="Test Patient",
            patient_phone="+15554444444",
            appointment_type_id=None,
            notified_at=datetime.now(timezone.utc),
        )
        mock_result = MagicMock()
        mock_result.fetchone.return_value = entry
        mock_update_result = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[mock_result, mock_update_result, mock_update_result, mock_update_result]
        )

        with patch(
            "app.scale.waitlist_notifier._send_waitlist_sms",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await process_waitlist_response(mock_db, "+15554444444", "yes")

        assert result["status"] == "booked"

    async def test_arbitrary_text_declines(self, mock_db):
        """Anything that is not YES/SI/Y/S should decline."""
        from app.scale.waitlist_notifier import process_waitlist_response

        entry = _make_row(
            id=uuid4(),
            practice_id=uuid4(),
            patient_name="Test Patient",
            patient_phone="+15555555555",
            appointment_type_id=None,
            notified_at=datetime.now(timezone.utc),
        )
        mock_result = MagicMock()
        mock_result.fetchone.return_value = entry
        mock_update_result = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[mock_result, mock_update_result]
        )

        result = await process_waitlist_response(mock_db, "+15555555555", "MAYBE")
        assert result["status"] == "declined"


class TestExpireStaleNotifications:
    """Tests for expire_stale_notifications."""

    async def test_expires_stale_entries(self, mock_db):
        from app.scale.waitlist_notifier import expire_stale_notifications

        expired_rows = [
            _make_row(id=uuid4(), practice_id=uuid4()),
            _make_row(id=uuid4(), practice_id=uuid4()),
        ]
        mock_result = MagicMock()
        mock_result.fetchall.return_value = expired_rows
        mock_db.execute = AsyncMock(return_value=mock_result)

        count = await expire_stale_notifications(mock_db)
        assert count == 2
        mock_db.commit.assert_awaited_once()

    async def test_no_stale_entries_returns_zero(self, mock_db):
        from app.scale.waitlist_notifier import expire_stale_notifications

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        count = await expire_stale_notifications(mock_db)
        assert count == 0
        # commit should NOT be called when nothing expired
        mock_db.commit.assert_not_awaited()
