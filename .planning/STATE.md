# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-08)

**Core value:** Patients get immediate, intelligent phone service without hold times
**Current focus:** Phase 3 - Webhook & Call Flow (hardening, status codes, persistence)

## Current Position

Phase: 3 of 8 (Webhook & Call Flow) -- COMPLETE
Plan: 2 of 2 in current phase
Status: Phase complete
Last activity: 2026-03-08 — Plan 03-02 complete: 44 webhook call flow tests covering HOOK-01 through HOOK-08

Progress: [████░░░░░░] ~35%

## Performance Metrics

**Velocity:**
- Total plans completed: 7
- Average duration: ~3 min
- Total execution time: ~19 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-configurable-settings | 2 | ~6 min | ~3 min |
| 02-schedule-management | 3 | 8 min | ~3 min |
| 03-webhook-call-flow | 2 | 5 min | ~3 min |

**Recent Trend:**
- Last 5 plans: 02-02 (3 min), 02-03 (2 min), 03-01 (2 min), 03-02 (3 min)
- Trend: stable

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

### Pending Todos

None yet.

### Blockers/Concerns

- Stedi API key not yet obtained (INS phase will need it or graceful fallback testing)

## Session Continuity

Last session: 2026-03-08
Stopped at: Completed 03-02-PLAN.md (44 webhook call flow tests, all HOOK requirements covered, Phase 3 complete)
Resume file: None
