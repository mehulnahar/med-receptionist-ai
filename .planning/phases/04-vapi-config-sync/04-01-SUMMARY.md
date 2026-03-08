---
phase: 04-vapi-config-sync
plan: 01
subsystem: api
tags: [vapi, httpx, voice-ai, config-sync, fastapi]

# Dependency graph
requires:
  - phase: 01-configurable-settings
    provides: "PracticeConfig model with vapi_* fields, config PUT endpoint, vapi_service.py"
provides:
  - "sync_assistant_config function: GET-merge-PATCH to Vapi assistant API"
  - "Config PUT auto-syncs prompt, voice, model, greeting changes to Vapi"
  - "vapi_sync_status field in PracticeConfigResponse for frontend sync feedback"
affects: [04-vapi-config-sync, frontend-settings-ui]

# Tech tracking
tech-stack:
  added: []
  patterns: ["GET-merge-PATCH for safe partial Vapi updates preserving existing tools"]

key-files:
  created: []
  modified:
    - backend/app/services/vapi_service.py
    - backend/app/routes/config.py
    - backend/app/schemas/practice_config.py

key-decisions:
  - "GET-merge-PATCH pattern: fetch current assistant config before patching to avoid clobbering tools/other model fields"
  - "Per-practice vapi_api_key with global fallback: supports multi-tenant while working in single-tenant"
  - "DB save independent of Vapi sync: config persists even when Vapi API is down"
  - "Structured error return dict instead of bool: enables frontend to display specific error messages"

patterns-established:
  - "Vapi sync pattern: detect changed fields in update_data, call sync after db.commit(), attach result to response"
  - "Error categorization: 401/403 -> 'Invalid API key', 429 -> 'Rate limit', 5xx -> 'Temporarily unavailable'"

requirements-completed: [VAPI-01, VAPI-02, VAPI-03, VAPI-04, VAPI-05]

# Metrics
duration: 2min
completed: 2026-03-08
---

# Phase 4 Plan 01: Vapi Config Sync Summary

**sync_assistant_config with GET-merge-PATCH pattern syncing prompt, voice, model, and greeting to Vapi assistant on config save**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-08T15:08:21Z
- **Completed:** 2026-03-08T15:09:59Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added sync_assistant_config to vapi_service.py: safely syncs system prompt, first message, model provider/name, and voice provider/ID to Vapi via GET-merge-PATCH
- Wired config PUT endpoint to detect Vapi-syncable field changes and trigger sync after DB commit
- Added vapi_sync_status field to PracticeConfigResponse so frontend can display sync success/failure
- Comprehensive error handling: 401/403, 429, 5xx, timeout, and unexpected errors all return descriptive messages

## Task Commits

Each task was committed atomically:

1. **Task 1 + Task 2: Add sync_assistant_config and wire config PUT** - `08a5b0d` (feat)

**Plan metadata:** pending (docs: complete plan)

## Files Created/Modified
- `backend/app/services/vapi_service.py` - Added sync_assistant_config function (GET-merge-PATCH to Vapi assistant API)
- `backend/app/routes/config.py` - Wired PUT endpoint to detect Vapi-syncable field changes and trigger sync, added imports
- `backend/app/schemas/practice_config.py` - Added vapi_sync_status optional field to PracticeConfigResponse

## Decisions Made
- **GET-merge-PATCH pattern**: Fetch current assistant config before patching to avoid accidentally removing existing tools, model settings, or voice config that Vapi stores but we don't track in DB
- **Per-practice API key with global fallback**: sync_assistant_config accepts per-practice vapi_api_key, falls back to global settings.VAPI_API_KEY for the single-tenant scenario
- **DB save independent of sync**: Config always persists to database first; Vapi sync is best-effort after commit, with status returned in response
- **Structured error dict**: Returns {"success": bool, "error": str|None} instead of just bool, so the frontend can surface specific error messages to the admin

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- sync_assistant_config is ready for testing in Plan 04-02
- Frontend can now display vapi_sync_status from config PUT responses
- The pattern established here (detect changed fields, sync after commit, attach status to response) can be extended for future Vapi features

## Self-Check: PASSED

All files verified present. Commit 08a5b0d confirmed in git log.

---
*Phase: 04-vapi-config-sync*
*Completed: 2026-03-08*
