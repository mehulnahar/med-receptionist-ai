---
phase: 03-webhook-call-flow
plan: 01
subsystem: api
tags: [webhooks, vapi, http-status, call-persistence, fastapi]

# Dependency graph
requires:
  - phase: 01-configurable-settings
    provides: PracticeConfig model for phone-based practice resolution
provides:
  - Hardened webhook endpoint with proper HTTP status codes (401/400)
  - Consolidated end-of-call persistence with all 5 HOOK-03 fields
  - save_end_of_call_report with structured_data and success_evaluation params
affects: [03-webhook-call-flow, 04-call-dashboard]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Webhook auth returns 401 (not 200) on signature failure"
    - "Malformed payloads return 400 (not 200) for clear error signaling"
    - "Structured data extraction consolidated into call_service layer"

key-files:
  created: []
  modified:
    - backend/app/routes/webhooks.py
    - backend/app/services/call_service.py

key-decisions:
  - "Moved structured_data/success_evaluation persistence from webhooks.py into save_end_of_call_report for single-responsibility"
  - "save_end_of_call_report now returns the Call object (used by callback flagging and feedback loop)"

patterns-established:
  - "Webhook error responses: 401 for auth, 400 for bad payload, 200 for all dispatched events"
  - "End-of-call fields consolidated in call_service, not scattered in webhook handler"

requirements-completed: [HOOK-01, HOOK-02, HOOK-03, HOOK-04]

# Metrics
duration: 2min
completed: 2026-03-08
---

# Phase 3 Plan 01: Webhook Hardening Summary

**Hardened webhook auth (401/400 status codes) and consolidated all 5 HOOK-03 end-of-call fields into save_end_of_call_report**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-08T14:48:08Z
- **Completed:** 2026-03-08T14:50:32Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Signature verification failures now return HTTP 401 (was 200)
- Malformed JSON and schema validation failures now return HTTP 400 (was 200)
- All 5 HOOK-03 required fields (recording_url, transcript, summary, structured_data, cost) consolidated into save_end_of_call_report
- Removed duplicate structured data saving block from webhooks.py

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix webhook auth to return 401 and malformed payloads to return 400** - `0c7e8b9` (feat)
2. **Task 2: Consolidate end-of-call report persistence** - `69a3907` (feat)

## Files Created/Modified
- `backend/app/routes/webhooks.py` - Changed status codes: auth failure -> 401, bad JSON -> 400, bad schema -> 400; removed duplicate structured data block; updated docstrings
- `backend/app/services/call_service.py` - Added structured_data and success_evaluation params to save_end_of_call_report; added inline extraction of caller_intent, caller_sentiment, language

## Decisions Made
- Moved structured data extraction logic (caller_intent, caller_sentiment, language mapping) from webhooks.py into call_service.py's save_end_of_call_report to consolidate all persistence in one place
- save_end_of_call_report return value now used directly as call_record in webhooks.py (eliminates a separate SELECT query)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Webhook endpoint hardened with proper status codes, ready for production
- End-of-call persistence fully consolidated, ready for call dashboard work (Phase 4)
- Plan 03-02 (webhook tests) can proceed as next step

## Self-Check: PASSED

- FOUND: backend/app/routes/webhooks.py
- FOUND: backend/app/services/call_service.py
- FOUND: .planning/phases/03-webhook-call-flow/03-01-SUMMARY.md
- FOUND: 0c7e8b9 (Task 1 commit)
- FOUND: 69a3907 (Task 2 commit)

---
*Phase: 03-webhook-call-flow*
*Completed: 2026-03-08*
