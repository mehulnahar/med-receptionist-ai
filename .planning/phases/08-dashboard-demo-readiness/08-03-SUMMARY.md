---
phase: 08-dashboard-demo-readiness
plan: 03
subsystem: testing
tags: [pytest, httpx, asgi-testclient, fastapi-dependency-overrides, integration-tests]

# Dependency graph
requires:
  - phase: 08-01
    provides: Seed data with 8 appointment types, 8 carriers, transfer_number
  - phase: 08-02
    provides: Dashboard status buttons and patient DOB search
  - phase: 06-appointment-booking
    provides: PATCH /appointments/{id}/status endpoint
provides:
  - 32 integration tests covering all DASH requirements (DASH-01 through DASH-10)
  - ASGI TestClient pattern with dependency overrides for auth and DB mocking
  - Verification that all 7 key API endpoints respond 200
  - Auth gate tests (401 without token)
  - Empty data edge case tests (empty lists, not errors)
affects: [08-04, demo, production-readiness]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "FastAPI dependency_overrides for auth and DB in ASGI tests"
    - "Rate limiter state clearing between test fixtures"
    - "Save/restore app.dependency_overrides for cross-test isolation"

key-files:
  created: [backend/tests/test_dashboard_demo.py]
  modified: []

key-decisions:
  - "Used ASGI TestClient with dependency overrides (not pure unit mocks) for realistic endpoint testing"
  - "Rate limit counter clearing in fixtures to prevent 429 in full suite runs"
  - "Admin create tests use mock refresh side_effect to set server-generated fields (id, timestamps)"
  - "Cost field compared via float() since Decimal serializes to string in JSON"

patterns-established:
  - "ASGI test client: override get_current_user and get_db via app.dependency_overrides"
  - "Fixture isolation: save/restore overrides dict to prevent cross-test leakage"
  - "_clear_rate_limit_state helper walks middleware stack to reset counters"

requirements-completed: [DASH-01, DASH-03, DASH-04, DASH-05, DASH-06, DASH-08, DASH-09, DASH-10]

# Metrics
duration: 13min
completed: 2026-03-08
---

# Phase 08 Plan 03: Dashboard and Demo Readiness Tests Summary

**32 integration tests via ASGI TestClient verifying all dashboard API endpoints, auth gates, status changes, and empty-data edge cases**

## Performance

- **Duration:** 13 min
- **Started:** 2026-03-08T16:34:15Z
- **Completed:** 2026-03-08T16:47:34Z
- **Tasks:** 1
- **Files created:** 1

## Accomplishments
- Created 32 integration tests organized into 9 test classes covering all DASH requirements
- Verified all 7 key API endpoints used by the 12 frontend pages return 200 (not 500)
- Confirmed unauthenticated requests return 401/403 across appointments, config, and calls endpoints
- Validated empty data scenarios return empty lists (not errors) for appointments, calls, analytics, and patient search
- Tested appointment status transitions (booked -> confirmed -> entered_in_ehr) via PATCH endpoint
- Verified call detail response includes recording_url, transcript, summary, duration_seconds, and cost
- Confirmed analytics overview returns chart-compatible nested structure (calls, appointments, patients, ai_performance)
- Validated practice config response includes all integration fields (Vapi, Twilio, Stedi, transfer, fallback)
- Tested admin CRUD (list and create for both practices and users)
- Verified patient search works by name, phone, and DOB, and returns 400 with no params
- Full test suite passes: 601 tests (569 existing + 32 new), zero regressions

## Task Commits

1. **Task 1: Create dashboard and demo readiness test suite** - `0d1cf8f` (feat)

## Files Created/Modified
- `backend/tests/test_dashboard_demo.py` - 32 integration tests covering DASH-01 through DASH-10, organized into 9 test classes (TestDashboardAppointments, TestCallLog, TestAnalytics, TestSettings, TestAdminPanel, TestPatientSearch, TestPageLoadPositive, TestAuthNegative, TestEmptyDataEdge)

## Decisions Made
- Used ASGI TestClient (httpx.ASGITransport) with FastAPI dependency overrides rather than pure unit test mocks. This tests the actual HTTP routing, middleware, and response serialization while mocking only auth and database layers.
- Implemented rate limiter counter clearing in test fixtures. The in-memory rate limiter tracks requests per IP, and the test client's shared 127.0.0.1 IP would trigger 429 Too Many Requests during full suite runs (30/min admin limit).
- Used save/restore pattern for `app.dependency_overrides` to prevent cross-test contamination when `unauth_client` clears overrides.
- Added `vapi_sync_status = None` explicitly to mock PracticeConfig objects because MagicMock auto-creates attributes as MagicMock instances, which fails Pydantic's `model_validate(from_attributes=True)`.
- For admin create endpoint tests, used `mock_db.refresh` side_effect to set server-generated fields (id, created_at, status) since real SQLAlchemy models need those populated after flush.
- Cost field assertion uses `float(c["cost"])` because Python's `Decimal` serializes to string in JSON responses.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed rate limiting 429 in full suite runs**
- **Found during:** Task 1 (test_admin_users_endpoint_responds)
- **Issue:** In-memory rate limiter's 30/min admin limit triggered by shared test client IP across all test files
- **Fix:** Added `_clear_rate_limit_state()` helper that walks the Starlette middleware stack and clears the request counter dict
- **Files modified:** backend/tests/test_dashboard_demo.py
- **Verification:** Full suite passes with 601 tests, zero 429 errors

**2. [Rule 1 - Bug] Fixed PracticeConfig mock missing vapi_sync_status**
- **Found during:** Task 1 (test_get_practice_config)
- **Issue:** MagicMock auto-creates attributes; Pydantic's model_validate expected dict|None but got MagicMock
- **Fix:** Explicitly set `cfg.vapi_sync_status = None` in _mock_practice_config
- **Files modified:** backend/tests/test_dashboard_demo.py
- **Verification:** Config endpoint tests pass with proper serialization

**3. [Rule 1 - Bug] Fixed Decimal cost assertion**
- **Found during:** Task 1 (test_call_detail_fields)
- **Issue:** JSON serializes Decimal("0.25") to string "0.25", not float 0.25
- **Fix:** Changed assertion to `float(c["cost"]) == 0.25`
- **Files modified:** backend/tests/test_dashboard_demo.py
- **Verification:** Call detail field test passes

---

**Total deviations:** 3 auto-fixed (2 bugs, 1 blocking)
**Impact on plan:** All auto-fixes necessary for test correctness. No scope creep.

## Issues Encountered
- Admin create endpoint tests initially patched the User/Practice model classes, which broke SQLAlchemy's `select()` constructor. Fixed by not patching models and instead using mock_db.refresh side_effect to set server-generated fields.
- Cross-test contamination from FastAPI dependency_overrides required save/restore pattern in fixtures.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 8 DASH requirements verified by automated tests
- 601 total tests passing with zero regressions
- Ready for 08-04 (final demo readiness verification)

## Self-Check: PASSED

- FOUND: backend/tests/test_dashboard_demo.py
- FOUND: commit 0d1cf8f
- FOUND: .planning/phases/08-dashboard-demo-readiness/08-03-SUMMARY.md

---
*Phase: 08-dashboard-demo-readiness*
*Completed: 2026-03-08*
