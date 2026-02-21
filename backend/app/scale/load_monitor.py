"""
Performance monitoring and alerting infrastructure.

Tracks latency for voice pipeline phases and API endpoints, calculates
percentiles, triggers alerts, and exports metrics in a format compatible
with Datadog / CloudWatch custom metrics.
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class LatencyRecord:
    timestamp: float
    duration_ms: float


@dataclass
class AlertThreshold:
    name: str
    metric: str  # phase name or "api_p95"
    threshold_ms: float
    window_minutes: int = 5
    severity: str = "warning"  # "warning" | "critical"


DEFAULT_THRESHOLDS: list[AlertThreshold] = [
    AlertThreshold("Voice total latency", "total", 1000.0, 5, "critical"),
    AlertThreshold("STT latency", "stt", 300.0, 5, "warning"),
    AlertThreshold("LLM latency", "llm", 500.0, 5, "warning"),
    AlertThreshold("TTS latency", "tts", 300.0, 5, "warning"),
    AlertThreshold("API P95 latency", "api_p95", 2000.0, 5, "critical"),
]


# ---------------------------------------------------------------------------
# PerformanceMonitor (singleton)
# ---------------------------------------------------------------------------

class PerformanceMonitor:
    """Tracks latency metrics with bounded memory and alerting."""

    _instance: Optional["PerformanceMonitor"] = None
    MAX_RECORDS = 10_000

    def __init__(self) -> None:
        self._call_latencies: dict[str, deque[LatencyRecord]] = {}
        self._api_latencies: deque[dict] = deque(maxlen=self.MAX_RECORDS)
        self._thresholds = list(DEFAULT_THRESHOLDS)

    @classmethod
    def get_instance(cls) -> "PerformanceMonitor":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    # ---- Recording ----

    def record_call_latency(
        self, call_id: str, phase: str, duration_ms: float
    ) -> None:
        """Record latency for a voice pipeline phase (stt, llm, tts, total)."""
        if phase not in self._call_latencies:
            self._call_latencies[phase] = deque(maxlen=self.MAX_RECORDS)
        self._call_latencies[phase].append(
            LatencyRecord(timestamp=time.time(), duration_ms=duration_ms)
        )

    def record_api_latency(
        self,
        endpoint: str,
        method: str,
        duration_ms: float,
        status_code: int,
    ) -> None:
        """Record latency for an API endpoint."""
        self._api_latencies.append(
            {
                "timestamp": time.time(),
                "endpoint": endpoint,
                "method": method,
                "duration_ms": duration_ms,
                "status_code": status_code,
            }
        )

    # ---- Querying ----

    def get_latency_percentiles(
        self, phase: str, window_minutes: int = 5
    ) -> dict:
        """Calculate p50, p95, p99, avg for a phase within a time window."""
        cutoff = time.time() - (window_minutes * 60)

        if phase == "api_p95":
            values = [
                r["duration_ms"]
                for r in self._api_latencies
                if r["timestamp"] >= cutoff
            ]
        else:
            records = self._call_latencies.get(phase, deque())
            values = [
                r.duration_ms for r in records if r.timestamp >= cutoff
            ]

        if not values:
            return {"p50": 0, "p95": 0, "p99": 0, "avg": 0, "count": 0}

        values.sort()
        n = len(values)
        return {
            "p50": round(values[int(n * 0.50)], 1),
            "p95": round(values[int(min(n * 0.95, n - 1))], 1),
            "p99": round(values[int(min(n * 0.99, n - 1))], 1),
            "avg": round(sum(values) / n, 1),
            "count": n,
        }

    # ---- Alerting ----

    def check_alerts(self) -> list[dict]:
        """Check all thresholds and return triggered alerts."""
        triggered = []
        for threshold in self._thresholds:
            stats = self.get_latency_percentiles(
                threshold.metric, threshold.window_minutes
            )
            # Use p95 as the comparison metric
            current_value = stats.get("p95", 0)
            if stats["count"] > 0 and current_value > threshold.threshold_ms:
                triggered.append(
                    {
                        "name": threshold.name,
                        "metric": threshold.metric,
                        "severity": threshold.severity,
                        "threshold_ms": threshold.threshold_ms,
                        "current_p95_ms": current_value,
                        "current_avg_ms": stats["avg"],
                        "sample_count": stats["count"],
                        "window_minutes": threshold.window_minutes,
                    }
                )
        return triggered

    # ---- Health score ----

    def health_score(self) -> int:
        """Calculate platform health score (0-100)."""
        score = 100
        alerts = self.check_alerts()
        for alert in alerts:
            if alert["severity"] == "critical":
                score -= 25
            elif alert["severity"] == "warning":
                score -= 10
        return max(0, score)

    # ---- Export ----

    def export_metrics(self) -> dict:
        """Export metrics in a format suitable for Datadog/CloudWatch."""
        now = time.time()
        phases = ["stt", "llm", "tts", "total"]
        metrics = {
            "timestamp": now,
            "voice_pipeline": {},
            "api": self.get_latency_percentiles("api_p95", 5),
            "health_score": self.health_score(),
            "alerts": self.check_alerts(),
        }
        for phase in phases:
            metrics["voice_pipeline"][phase] = self.get_latency_percentiles(
                phase, 5
            )

        # Error rate from API latencies
        cutoff = now - 300  # 5 min
        recent_api = [
            r for r in self._api_latencies if r["timestamp"] >= cutoff
        ]
        if recent_api:
            errors = sum(1 for r in recent_api if r["status_code"] >= 500)
            metrics["api"]["error_rate_pct"] = round(
                errors / len(recent_api) * 100, 2
            )
            metrics["api"]["total_requests"] = len(recent_api)
        else:
            metrics["api"]["error_rate_pct"] = 0
            metrics["api"]["total_requests"] = 0

        return metrics
