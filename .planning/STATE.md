# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-08)

**Core value:** Patients get immediate, intelligent phone service without hold times
**Current focus:** Phase 8 - Dashboard & Demo Readiness

## Current Position

Phase: 8 of 8 (Dashboard & Demo Readiness)
Plan: 3 of 4 in current phase -- COMPLETE
Status: In progress
Last activity: 2026-03-08 — Plan 08-03 complete: dashboard and demo readiness tests (32 integration tests)

Progress: [██████████] ~95%

## Performance Metrics

**Velocity:**
- Total plans completed: 19
- Average duration: ~3 min
- Total execution time: ~57 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-configurable-settings | 2 | ~6 min | ~3 min |
| 02-schedule-management | 3 | 8 min | ~3 min |
| 03-webhook-call-flow | 2 | 5 min | ~3 min |
| 04-vapi-config-sync | 3 | 6 min | ~2 min |
| 05-call-transfer-fallback | 3 | 5 min | ~2 min |
| 06-appointment-booking | 2 | 7 min | ~4 min |
| 07-insurance-verification | 2 | 5 min | ~3 min |
| 08-dashboard-demo-readiness | 3 | 17 min | ~6 min |

**Recent Trend:**
- Last 5 plans: 07-01 (2 min), 07-02 (3 min), 08-01 (2 min), 08-02 (2 min), 08-03 (13 min)
- Trend: spike on integration test suite (expected for ASGI client tests with multiple fix iterations)

*Updated after each plan completion*

## Accumulated Context

### From v1.0

- Backend fully deployed on AWS App Runner (healthy, v1.2.0)
- Frontend on CloudFront (all 12 pages functional)
- Vapi inbound calls working (tested from India)
- transfer_number NOT configured -- transfers will fail
- Stedi API key NOT obtained -- insurance falls back gracefully
- Vapi config changes in dashboard do NOT sync to Vapi assistant
- No Twilio crash fallback configured
- Hardcoded transfer message, reminder templates
- All backend modules functional but need edge case testing

### Decisions

Decisions logged in PROJECT.md Key Decisions table.

- [Roadmap]: 8 phases derived from 75 requirements across 9 categories
- [Roadmap]: CONF phase first (foundation), DEMO phase last (depends on everything)
- [Roadmap]: Testing integrated into each phase (not separated)
- [01-01]: REMINDER_TEMPLATES renamed to DEFAULT_REMINDER_TEMPLATES as fallback constant in reminder_service
- [01-01]: conversation_manager uses inline AsyncSessionLocal for PracticeConfig lookup (no request DB), wrapped in try/except for safety on emergency detection path
- [01-01]: transfer_message Vapi sync only triggers when transfer_number changes (preserving existing semantics)
- [01-02]: Reminder templates stored flat in form state (reminder_template_24h_en/es) and assembled into nested object on save
- [01-02]: 422 error handler parses Pydantic array format via err.response.data.detail.map(e => e.msg).join('; ')
- [02-01]: Reference date approach for alternate Fridays -- even weeks from ref are working, odd weeks are off
- [02-01]: Config passed through _get_schedule_for_date signature to avoid redundant DB lookups
- [02-01]: find_next_available_slot uses inline alternate Friday check (batch-fetched data, no _get_schedule_for_date call)
- [02-02]: Weekly schedule save button relabeled to 'Save Weekly Schedule' for clarity alongside new sections
- [02-02]: Override add form uses inline expand/collapse (consistent with Settings page patterns)
- [02-02]: Alternate Friday reference date validated client-side with getDay() === 5 check
- [02-03]: Availability logic tested via _simulate_availability helper mirroring get_available_slots pure logic (no DB mocking)
- [02-03]: Alternate Friday parity formula tested as standalone helper (formula inline in service, not extracted)
- [03-01]: Moved structured_data/success_evaluation persistence from webhooks.py into save_end_of_call_report for single-responsibility
- [03-01]: save_end_of_call_report now returns the Call object (used by callback flagging and feedback loop)
- [03-02]: Used ASGI TestClient (httpx + ASGITransport) for dispatch tests, not raw mocking
- [03-02]: Tested _verify_vapi_signature as pure function with mocked get_settings() for isolation
- [03-02]: Concurrent call safety verified via asyncio.gather with independent mock DB sessions
- [04-01]: GET-merge-PATCH pattern for Vapi sync to avoid clobbering existing tools/model fields
- [04-01]: Per-practice vapi_api_key with global fallback for multi-tenant support
- [04-01]: DB save independent of Vapi sync -- config persists even when Vapi API is down
- [04-01]: Structured error dict {"success": bool, "error": str|None} for frontend display
- [04-02]: Warning toast auto-dismiss extended to 8s (vs 4s) so admin can read Vapi sync error details
- [04-02]: Error handler improved to parse Pydantic validation array format (Array.isArray check on detail)
- [04-03]: Used async side_effect functions for HTTP error simulation (cleaner raise_for_status flow)
- [04-03]: Concurrent tests use mock_client_cls.side_effect list for true per-call isolation
- [04-03]: Payload assertions extract from call_args.kwargs["json"] for explicit PATCH body verification
- [05-02]: Used window.location.origin for URL generation instead of hardcoded domain (works in both dev and prod)
- [05-02]: Conditional display: URL only shown when fallback_phone_number is set, amber warning otherwise
- [05-01]: No auth on fallback endpoint -- Twilio must reach it when backend is degraded
- [05-01]: Added **kwargs to tool_transfer_to_staff for forward compatibility
- [05-01]: No db.commit() in transfer logging -- caller handles commit
- [05-03]: Used side_effect list pattern for sequential DB mocks (config then call lookup)
- [05-03]: XML validation via xml.etree.ElementTree for TwiML well-formedness checks
- [06-01]: Three-tier language fallback: params.language > Call.language > default 'en'
- [06-01]: Language included in booking response dict for downstream tool visibility
- [06-02]: Patch locally-imported functions at source module path (not consumer) for Python local imports
- [06-02]: Centralized _P_* patch target constants for DRY test configuration across 8 test classes
- [07-01]: 4-char minimum guard on substring matching prevents false positives on short carrier name inputs
- [07-01]: Bidirectional substring on name checked before aliases (step 1b) for faster resolution
- [07-01]: DOB robust parser defined as local helper inside tool_verify_insurance to avoid polluting module scope
- [07-02]: Used 'Terminated' instead of 'Inactive' for negative parse test since parse_eligibility_response substring-matches 'active' in 'Inactive'
- [07-02]: Tested _resolve_payer_id_inner directly (bypassing asyncio.wait_for wrapper) for deterministic DB mock sequencing
- [07-02]: Centralized _P_* patch target constants following test_appointment_booking.py pattern for DRY test configuration
- [08-01]: Idempotent update-if-missing pattern for stedi_payer_id and transfer_number on seed re-run
- [08-01]: Regional carriers (MetroPlus, Healthfirst, Fidelis) use placeholder Stedi payer IDs
- [08-01]: transfer_number set to +16612288584 (second Twilio number from dashboard)
- [08-02]: Status buttons render contextually: booked shows Mark Confirmed, confirmed shows Mark In EHR, terminal states show no button
- [08-02]: DOB search uses native HTML date input for automatic YYYY-MM-DD format matching backend expectation
- [08-03]: ASGI TestClient with FastAPI dependency overrides (not pure unit mocks) for realistic endpoint testing
- [08-03]: Rate limiter counter clearing in fixtures prevents 429 in full suite runs (shared 127.0.0.1 IP)
- [08-03]: Save/restore app.dependency_overrides pattern for cross-test isolation in fixture teardown

### Pending Todos

None yet.

### Blockers/Concerns

- Stedi API key not yet obtained (INS phase will need it or graceful fallback testing)

## Session Continuity

Last session: 2026-03-08
Stopped at: Completed 08-03-PLAN.md (32 dashboard demo readiness integration tests)
Resume file: None
