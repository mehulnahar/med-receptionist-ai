"""
Monitoring & load testing API routes.
"""

import asyncio
import logging
import random
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_practice_admin
from app.models.user import User
from app.scale.concurrent_calls import ConcurrentCallManager
from app.scale.load_monitor import PerformanceMonitor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/monitoring", tags=["Monitoring"])


# ---------------------------------------------------------------------------
# Load test runner
# ---------------------------------------------------------------------------

class LoadTestConfig(BaseModel):
    num_calls: int = Field(10, ge=1, le=100)
    duration_seconds: int = Field(30, ge=5, le=300)
    ramp_up_seconds: int = Field(5, ge=0, le=60)


class LoadTestStatus(BaseModel):
    test_id: str
    status: str  # "running" | "completed" | "failed"
    progress_pct: float
    calls_started: int
    calls_completed: int
    calls_failed: int
    elapsed_seconds: float


_active_tests: dict[str, dict] = {}


async def _simulate_call(
    test_state: dict,
    call_idx: int,
    monitor: PerformanceMonitor,
) -> None:
    """Simulate a single call through the voice pipeline."""
    call_id = f"loadtest-{test_state['test_id']}-{call_idx}"
    try:
        test_state["calls_started"] += 1

        # Simulate STT
        stt_ms = random.uniform(50, 250)
        await asyncio.sleep(stt_ms / 1000)
        monitor.record_call_latency(call_id, "stt", stt_ms)

        # Simulate LLM
        llm_ms = random.uniform(100, 400)
        await asyncio.sleep(llm_ms / 1000)
        monitor.record_call_latency(call_id, "llm", llm_ms)

        # Simulate TTS
        tts_ms = random.uniform(50, 200)
        await asyncio.sleep(tts_ms / 1000)
        monitor.record_call_latency(call_id, "tts", tts_ms)

        total_ms = stt_ms + llm_ms + tts_ms
        monitor.record_call_latency(call_id, "total", total_ms)

        test_state["calls_completed"] += 1
    except Exception as e:
        test_state["calls_failed"] += 1
        logger.warning("Load test call %s failed: %s", call_id, e)


async def _run_load_test(test_id: str, config: LoadTestConfig) -> None:
    """Execute a load test by ramping up simulated calls."""
    state = _active_tests[test_id]
    monitor = PerformanceMonitor.get_instance()

    state["status"] = "running"
    state["start_time"] = time.time()

    try:
        delay_per_call = (
            config.ramp_up_seconds / config.num_calls
            if config.num_calls > 0
            else 0
        )

        tasks = []
        for i in range(config.num_calls):
            if state["status"] == "cancelled":
                break
            task = asyncio.create_task(
                _simulate_call(state, i, monitor)
            )
            tasks.append(task)
            if delay_per_call > 0:
                await asyncio.sleep(delay_per_call)

        # Wait for all calls to finish (up to duration limit)
        remaining = config.duration_seconds - (time.time() - state["start_time"])
        if remaining > 0 and tasks:
            await asyncio.wait(tasks, timeout=remaining)

        state["status"] = "completed"
    except Exception as e:
        state["status"] = "failed"
        logger.error("Load test %s failed: %s", test_id, e)
    finally:
        state["end_time"] = time.time()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin required")
    return current_user


@router.get("/metrics")
async def get_metrics(current_user: User = Depends(_require_super_admin)):
    """Export platform metrics for Datadog/CloudWatch."""
    monitor = PerformanceMonitor.get_instance()
    return monitor.export_metrics()


@router.get("/alerts")
async def get_alerts(
    current_user: User = Depends(require_practice_admin),
):
    """Check for active performance alerts."""
    monitor = PerformanceMonitor.get_instance()
    alerts = monitor.check_alerts()
    return {
        "alerts": alerts,
        "health_score": monitor.health_score(),
        "total_alerts": len(alerts),
        "critical_count": sum(1 for a in alerts if a["severity"] == "critical"),
    }


@router.get("/active-calls")
async def get_active_calls(current_user: User = Depends(_require_super_admin)):
    """Get concurrent call statistics."""
    manager = ConcurrentCallManager.get_instance()
    return {
        "stats": await manager.get_stats(),
        "calls": await manager.get_active_calls(),
    }


@router.get("/health-score")
async def get_health_score():
    """Public health score endpoint for load balancers."""
    monitor = PerformanceMonitor.get_instance()
    score = monitor.health_score()
    return {"health_score": score, "status": "healthy" if score >= 50 else "degraded"}


@router.post("/load-test/start")
async def start_load_test(
    config: LoadTestConfig,
    current_user: User = Depends(_require_super_admin),
):
    """Start a simulated load test."""
    test_id = str(uuid.uuid4())[:8]
    state = {
        "test_id": test_id,
        "status": "starting",
        "config": config.model_dump(),
        "calls_started": 0,
        "calls_completed": 0,
        "calls_failed": 0,
        "start_time": None,
        "end_time": None,
    }
    _active_tests[test_id] = state
    asyncio.create_task(_run_load_test(test_id, config))

    logger.info(
        "Load test started: id=%s calls=%d duration=%ds",
        test_id,
        config.num_calls,
        config.duration_seconds,
    )
    return {"test_id": test_id, "status": "starting"}


@router.get("/load-test/{test_id}/status")
async def get_load_test_status(
    test_id: str,
    current_user: User = Depends(_require_super_admin),
):
    """Check load test progress."""
    state = _active_tests.get(test_id)
    if not state:
        raise HTTPException(status_code=404, detail="Load test not found")

    elapsed = 0.0
    if state["start_time"]:
        end = state.get("end_time") or time.time()
        elapsed = round(end - state["start_time"], 1)

    total = state["config"]["num_calls"]
    done = state["calls_completed"] + state["calls_failed"]
    progress = round(done / total * 100, 1) if total > 0 else 0

    return LoadTestStatus(
        test_id=test_id,
        status=state["status"],
        progress_pct=progress,
        calls_started=state["calls_started"],
        calls_completed=state["calls_completed"],
        calls_failed=state["calls_failed"],
        elapsed_seconds=elapsed,
    )
