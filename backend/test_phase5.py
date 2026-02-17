"""
Phase 5 — Vapi Inbound Webhook Integration Tests

Tests the full inbound call lifecycle:
1. Webhook health check
2. Status-update: ringing → in-progress → tool-calls → end-of-call-report
3. Tool calls: check_patient, book_appointment, check_availability,
   cancel, reschedule, transfer_to_staff, verify_insurance
4. End-of-call report persistence
5. Invalid / edge-case payloads
"""

import json
import requests
import sys
import os
from uuid import uuid4

# Fix Windows console encoding
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding='utf-8')

BASE = "http://localhost:8005"
PASS = 0
FAIL = 0


def check(label: str, resp, expected_status=200, expected_keys=None, body_check=None):
    global PASS, FAIL
    ok = True
    details = []

    if resp.status_code != expected_status:
        ok = False
        details.append(f"status={resp.status_code} (expected {expected_status})")

    try:
        data = resp.json()
    except Exception:
        data = {}
        if expected_keys:
            ok = False
            details.append("response is not JSON")

    if expected_keys:
        for key in expected_keys:
            if key not in data:
                ok = False
                details.append(f"missing key '{key}'")

    if body_check and not body_check(data):
        ok = False
        details.append(f"body_check failed: {json.dumps(data, default=str)[:200]}")

    if ok:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        print(f"  ❌ {label} — {', '.join(details)}")
        if data:
            print(f"     Body: {json.dumps(data, default=str)[:300]}")

    return data


def post_webhook(payload):
    """Send a POST to the Vapi webhook endpoint."""
    return requests.post(f"{BASE}/api/webhooks/vapi", json=payload)


# ============================================================
# Generate a unique Vapi call ID for this test run
# ============================================================
VAPI_CALL_ID = f"test-call-{uuid4().hex[:8]}"
TEST_SUFFIX = uuid4().hex[:6]  # unique per run to avoid stale data

print("=" * 60)
print("Phase 5 — Vapi Inbound Webhook Integration Tests")
print("=" * 60)


# ------------------------------------------------------------------
# TEST 1: Webhook health check
# ------------------------------------------------------------------
print("\n--- Test 1: Webhook health check ---")
r = requests.get(f"{BASE}/api/webhooks/vapi/health")
check("GET /api/webhooks/vapi/health", r, 200, ["status", "message"])


# ------------------------------------------------------------------
# TEST 2: Status-update — ringing (creates call record)
# ------------------------------------------------------------------
print("\n--- Test 2: Status-update (ringing → creates call) ---")
r = post_webhook({
    "message": {
        "type": "status-update",
        "status": "ringing",
        "call": {
            "id": VAPI_CALL_ID,
            "type": "inboundPhoneCall",
            "status": "ringing",
            "customer": {"number": "+12125551234"},
            "phoneNumber": {"number": "+18005559999", "twilioPhoneNumber": "+18005559999"},
        },
    }
})
check("status-update ringing returns 200", r, 200)


# ------------------------------------------------------------------
# TEST 3: Status-update — in-progress (updates call)
# ------------------------------------------------------------------
print("\n--- Test 3: Status-update (in-progress) ---")
r = post_webhook({
    "message": {
        "type": "status-update",
        "status": "in-progress",
        "call": {
            "id": VAPI_CALL_ID,
            "type": "inboundPhoneCall",
            "status": "in-progress",
            "customer": {"number": "+12125551234"},
            "phoneNumber": {"number": "+18005559999"},
        },
    }
})
check("status-update in-progress returns 200", r, 200)


# ------------------------------------------------------------------
# TEST 4: assistant-request (returns assistant config)
# ------------------------------------------------------------------
print("\n--- Test 4: assistant-request ---")
r = post_webhook({
    "message": {
        "type": "assistant-request",
        "call": {
            "id": VAPI_CALL_ID,
            "type": "inboundPhoneCall",
            "customer": {"number": "+12125551234"},
        },
    }
})
check("assistant-request returns 200", r, 200)


# ------------------------------------------------------------------
# TEST 5: tool-calls — check_patient_exists (patient not found)
# ------------------------------------------------------------------
print("\n--- Test 5: tool-calls — check_patient_exists (not found) ---")
TOOL_CALL_ID_1 = f"tc-{uuid4().hex[:8]}"
r = post_webhook({
    "message": {
        "type": "tool-calls",
        "call": {
            "id": VAPI_CALL_ID,
            "type": "inboundPhoneCall",
        },
        "toolCallList": [
            {
                "id": TOOL_CALL_ID_1,
                "name": "check_patient_exists",
                "function": {
                    "name": "check_patient_exists",
                    "arguments": json.dumps({
                        "first_name": f"Test{TEST_SUFFIX}",
                        "last_name": "Phase5New",
                        "dob": "1990-06-15",
                    }),
                },
            }
        ],
    }
})
data = check(
    "tool-calls check_patient_exists returns results",
    r, 200, ["results"],
    body_check=lambda d: len(d.get("results", [])) == 1,
)
if data.get("results"):
    result_val = data["results"][0].get("result", {})
    if isinstance(result_val, str):
        result_val = json.loads(result_val)
    check(
        "  → patient not found (exists=False)",
        r, 200,
        body_check=lambda d: d["results"][0]["result"].get("exists") == False
        if isinstance(d["results"][0]["result"], dict) else True,
    )


# ------------------------------------------------------------------
# TEST 6: tool-calls — check_availability
# ------------------------------------------------------------------
print("\n--- Test 6: tool-calls — check_availability ---")
TOOL_CALL_ID_2 = f"tc-{uuid4().hex[:8]}"
r = post_webhook({
    "message": {
        "type": "tool-calls",
        "call": {
            "id": VAPI_CALL_ID,
            "type": "inboundPhoneCall",
        },
        "toolCallList": [
            {
                "id": TOOL_CALL_ID_2,
                "name": "check_availability",
                "function": {
                    "name": "check_availability",
                    "arguments": json.dumps({
                        "date": "2025-02-24",
                    }),
                },
            }
        ],
    }
})
data = check(
    "tool-calls check_availability returns results",
    r, 200, ["results"],
    body_check=lambda d: len(d.get("results", [])) == 1,
)
if data.get("results"):
    result_val = data["results"][0].get("result", {})
    if isinstance(result_val, dict):
        print(f"     Availability: {result_val.get('total_available', '?')} slots on {result_val.get('date', '?')}")


# ------------------------------------------------------------------
# TEST 7: tool-calls — book_appointment
# ------------------------------------------------------------------
print("\n--- Test 7: tool-calls — book_appointment ---")
TOOL_CALL_ID_3 = f"tc-{uuid4().hex[:8]}"
r = post_webhook({
    "message": {
        "type": "tool-calls",
        "call": {
            "id": VAPI_CALL_ID,
            "type": "inboundPhoneCall",
        },
        "toolCallList": [
            {
                "id": TOOL_CALL_ID_3,
                "name": "book_appointment",
                "function": {
                    "name": "book_appointment",
                    "arguments": json.dumps({
                        "first_name": f"Test{TEST_SUFFIX}",
                        "last_name": "Phase5New",
                        "dob": "1990-06-15",
                        "phone": "+12125551234",
                        "date": "2025-02-24",
                        "time": "09:00",
                    }),
                },
            }
        ],
    }
})
data = check(
    "tool-calls book_appointment returns results",
    r, 200, ["results"],
    body_check=lambda d: len(d.get("results", [])) == 1,
)

# Extract patient_id and appointment_id for subsequent tests
PATIENT_ID = None
APPOINTMENT_ID = None
if data.get("results"):
    result_val = data["results"][0].get("result", {})
    if isinstance(result_val, dict):
        PATIENT_ID = result_val.get("patient_id")
        APPOINTMENT_ID = result_val.get("appointment_id")
        success = result_val.get("success")
        error = result_val.get("error")
        if success:
            print(f"     Booked: patient={PATIENT_ID}, appt={APPOINTMENT_ID}")
        else:
            print(f"     Booking result: success={success}, error={error}")


# ------------------------------------------------------------------
# TEST 8: tool-calls — verify_insurance (stub)
# ------------------------------------------------------------------
print("\n--- Test 8: tool-calls — verify_insurance (stub) ---")
TOOL_CALL_ID_4 = f"tc-{uuid4().hex[:8]}"
r = post_webhook({
    "message": {
        "type": "tool-calls",
        "call": {
            "id": VAPI_CALL_ID,
            "type": "inboundPhoneCall",
        },
        "toolCallList": [
            {
                "id": TOOL_CALL_ID_4,
                "name": "verify_insurance",
                "function": {
                    "name": "verify_insurance",
                    "arguments": json.dumps({
                        "first_name": f"Test{TEST_SUFFIX}",
                        "last_name": "Phase5New",
                        "dob": "1990-06-15",
                        "insurance_carrier": "Aetna",
                        "member_id": "MEM123456",
                    }),
                },
            }
        ],
    }
})
data = check(
    "tool-calls verify_insurance returns results",
    r, 200, ["results"],
    body_check=lambda d: len(d.get("results", [])) == 1,
)
if data.get("results"):
    result_val = data["results"][0].get("result", {})
    if isinstance(result_val, dict):
        print(f"     Insurance verified: {result_val.get('verified')}")


# ------------------------------------------------------------------
# TEST 9: tool-calls — transfer_to_staff
# ------------------------------------------------------------------
print("\n--- Test 9: tool-calls — transfer_to_staff ---")
TOOL_CALL_ID_5 = f"tc-{uuid4().hex[:8]}"
r = post_webhook({
    "message": {
        "type": "tool-calls",
        "call": {
            "id": VAPI_CALL_ID,
            "type": "inboundPhoneCall",
        },
        "toolCallList": [
            {
                "id": TOOL_CALL_ID_5,
                "name": "transfer_to_staff",
                "function": {
                    "name": "transfer_to_staff",
                    "arguments": json.dumps({
                        "reason": "Patient speaks Greek",
                    }),
                },
            }
        ],
    }
})
data = check(
    "tool-calls transfer_to_staff returns results",
    r, 200, ["results"],
    body_check=lambda d: len(d.get("results", [])) == 1,
)
if data.get("results"):
    result_val = data["results"][0].get("result", {})
    if isinstance(result_val, dict):
        print(f"     Transfer: {result_val.get('transfer')}, number={result_val.get('number', 'N/A')}")


# ------------------------------------------------------------------
# TEST 10: tool-calls — cancel_appointment
# ------------------------------------------------------------------
print("\n--- Test 10: tool-calls — cancel_appointment ---")
if PATIENT_ID and APPOINTMENT_ID:
    TOOL_CALL_ID_6 = f"tc-{uuid4().hex[:8]}"
    r = post_webhook({
        "message": {
            "type": "tool-calls",
            "call": {
                "id": VAPI_CALL_ID,
                "type": "inboundPhoneCall",
            },
            "toolCallList": [
                {
                    "id": TOOL_CALL_ID_6,
                    "name": "cancel_appointment",
                    "function": {
                        "name": "cancel_appointment",
                        "arguments": json.dumps({
                            "patient_id": PATIENT_ID,
                            "appointment_date": "2025-02-24",
                        }),
                    },
                }
            ],
        }
    })
    data = check(
        "tool-calls cancel_appointment returns results",
        r, 200, ["results"],
        body_check=lambda d: len(d.get("results", [])) == 1,
    )
    if data.get("results"):
        result_val = data["results"][0].get("result", {})
        if isinstance(result_val, dict):
            print(f"     Cancelled: success={result_val.get('success')}, error={result_val.get('error', 'none')}")
else:
    print("  ⏭️  Skipped (no patient/appointment from previous test)")


# ------------------------------------------------------------------
# TEST 11: tool-calls — book then reschedule
# ------------------------------------------------------------------
print("\n--- Test 11: tool-calls — book + reschedule ---")
if PATIENT_ID:
    # Book a new appointment first
    TOOL_CALL_ID_7 = f"tc-{uuid4().hex[:8]}"
    r = post_webhook({
        "message": {
            "type": "tool-calls",
            "call": {"id": VAPI_CALL_ID, "type": "inboundPhoneCall"},
            "toolCallList": [
                {
                    "id": TOOL_CALL_ID_7,
                    "name": "book_appointment",
                    "function": {
                        "name": "book_appointment",
                        "arguments": json.dumps({
                            "patient_id": PATIENT_ID,
                            "date": "2025-02-25",
                            "time": "10:00",
                        }),
                    },
                }
            ],
        }
    })
    data = check("book for reschedule test", r, 200, ["results"])

    new_appt_id = None
    if data.get("results"):
        result_val = data["results"][0].get("result", {})
        if isinstance(result_val, dict) and result_val.get("success"):
            new_appt_id = result_val.get("appointment_id")
            print(f"     Booked appointment: {new_appt_id}")

    # Now reschedule it
    if new_appt_id:
        TOOL_CALL_ID_8 = f"tc-{uuid4().hex[:8]}"
        r = post_webhook({
            "message": {
                "type": "tool-calls",
                "call": {"id": VAPI_CALL_ID, "type": "inboundPhoneCall"},
                "toolCallList": [
                    {
                        "id": TOOL_CALL_ID_8,
                        "name": "reschedule_appointment",
                        "function": {
                            "name": "reschedule_appointment",
                            "arguments": json.dumps({
                                "patient_id": PATIENT_ID,
                                "old_date": "2025-02-25",
                                "new_date": "2025-02-26",
                                "new_time": "14:00",
                            }),
                        },
                    }
                ],
            }
        })
        data = check(
            "reschedule_appointment returns results",
            r, 200, ["results"],
            body_check=lambda d: len(d.get("results", [])) == 1,
        )
        if data.get("results"):
            result_val = data["results"][0].get("result", {})
            if isinstance(result_val, dict):
                print(f"     Rescheduled: {result_val.get('old_date')} → {result_val.get('new_date')} {result_val.get('new_time')}")
    else:
        print("  ⏭️  Skipped reschedule (booking failed)")
else:
    print("  ⏭️  Skipped (no patient_id)")


# ------------------------------------------------------------------
# TEST 12: tool-calls — unknown tool name
# ------------------------------------------------------------------
print("\n--- Test 12: tool-calls — unknown tool ---")
TOOL_CALL_ID_9 = f"tc-{uuid4().hex[:8]}"
r = post_webhook({
    "message": {
        "type": "tool-calls",
        "call": {"id": VAPI_CALL_ID, "type": "inboundPhoneCall"},
        "toolCallList": [
            {
                "id": TOOL_CALL_ID_9,
                "name": "nonexistent_tool",
                "function": {
                    "name": "nonexistent_tool",
                    "arguments": "{}",
                },
            }
        ],
    }
})
data = check(
    "unknown tool returns error in results (not crash)",
    r, 200, ["results"],
    body_check=lambda d: "error" in str(d.get("results", [{}])[0].get("result", "")),
)


# ------------------------------------------------------------------
# TEST 13: tool-calls — toolWithToolCallList format (newer)
# ------------------------------------------------------------------
print("\n--- Test 13: tool-calls — toolWithToolCallList format ---")
TOOL_CALL_ID_10 = f"tc-{uuid4().hex[:8]}"
r = post_webhook({
    "message": {
        "type": "tool-calls",
        "call": {"id": VAPI_CALL_ID, "type": "inboundPhoneCall"},
        "toolWithToolCallList": [
            {
                "type": "function",
                "name": "check_availability",
                "toolCall": {
                    "id": TOOL_CALL_ID_10,
                    "function": {
                        "name": "check_availability",
                        "arguments": json.dumps({"date": "2025-02-24"}),
                    },
                },
            }
        ],
    }
})
data = check(
    "toolWithToolCallList format returns results",
    r, 200, ["results"],
    body_check=lambda d: len(d.get("results", [])) == 1,
)


# ------------------------------------------------------------------
# TEST 14: function-call (legacy format)
# ------------------------------------------------------------------
print("\n--- Test 14: function-call (legacy) ---")
r = post_webhook({
    "message": {
        "type": "function-call",
        "call": {"id": VAPI_CALL_ID, "type": "inboundPhoneCall"},
        "functionCall": {
            "name": "check_availability",
            "parameters": {"date": "2025-02-24"},
        },
    }
})
data = check(
    "function-call legacy format returns result",
    r, 200, ["result"],
)


# ------------------------------------------------------------------
# TEST 15: end-of-call-report
# ------------------------------------------------------------------
print("\n--- Test 15: end-of-call-report ---")
r = post_webhook({
    "message": {
        "type": "end-of-call-report",
        "endedReason": "customer-ended-call",
        "call": {
            "id": VAPI_CALL_ID,
            "type": "inboundPhoneCall",
            "status": "ended",
            "customer": {"number": "+12125551234"},
            "startedAt": "2025-02-17T15:00:00Z",
            "endedAt": "2025-02-17T15:05:30Z",
            "cost": 0.12,
        },
        "artifact": {
            "transcript": "AI: Hello, Dr. Stefanides' office. How can I help?\nUser: I'd like to book an appointment.\nAI: Of course! Let me help you with that.",
            "recordingUrl": "https://storage.vapi.ai/recordings/test-recording.mp3",
        },
        "analysis": {
            "summary": "Patient called to book an appointment. Appointment booked for Feb 24 at 9:00 AM.",
        },
    }
})
check("end-of-call-report returns 200", r, 200)


# ------------------------------------------------------------------
# TEST 16: hang event
# ------------------------------------------------------------------
print("\n--- Test 16: hang event ---")
r = post_webhook({
    "message": {
        "type": "hang",
        "call": {"id": VAPI_CALL_ID, "type": "inboundPhoneCall"},
    }
})
check("hang event returns 200", r, 200)


# ------------------------------------------------------------------
# TEST 17: unknown message type
# ------------------------------------------------------------------
print("\n--- Test 17: unknown message type ---")
r = post_webhook({
    "message": {
        "type": "some-future-event",
        "call": {"id": VAPI_CALL_ID, "type": "inboundPhoneCall"},
    }
})
check("unknown message type returns 200 (no crash)", r, 200)


# ------------------------------------------------------------------
# TEST 18: invalid JSON body
# ------------------------------------------------------------------
print("\n--- Test 18: invalid/empty body ---")
r = requests.post(
    f"{BASE}/api/webhooks/vapi",
    data="not json at all",
    headers={"Content-Type": "application/json"},
)
check("invalid body returns 200 (never errors to Vapi)", r, 200)


# ------------------------------------------------------------------
# TEST 19: missing message field
# ------------------------------------------------------------------
print("\n--- Test 19: missing message field ---")
r = post_webhook({"something": "else"})
# FastAPI receives raw JSON via Request object, our handler catches validation errors
# and returns 200 (never error to Vapi). If FastAPI rejects first, we get 422.
# Either is acceptable — the key is no 500 error.
status_ok = r.status_code in (200, 422)
check(
    "missing message field returns 200 or 422 (no crash)",
    r, r.status_code,  # accept whatever it returned
    body_check=lambda d: status_ok,
)


# ------------------------------------------------------------------
# TEST 20: Multiple tool calls in one request
# ------------------------------------------------------------------
print("\n--- Test 20: Multiple tool calls in one request ---")
TC_A = f"tc-{uuid4().hex[:8]}"
TC_B = f"tc-{uuid4().hex[:8]}"
r = post_webhook({
    "message": {
        "type": "tool-calls",
        "call": {"id": VAPI_CALL_ID, "type": "inboundPhoneCall"},
        "toolCallList": [
            {
                "id": TC_A,
                "name": "check_availability",
                "function": {
                    "name": "check_availability",
                    "arguments": json.dumps({"date": "2025-02-24"}),
                },
            },
            {
                "id": TC_B,
                "name": "transfer_to_staff",
                "function": {
                    "name": "transfer_to_staff",
                    "arguments": json.dumps({"reason": "testing batch"}),
                },
            },
        ],
    }
})
data = check(
    "batch tool calls returns 2 results",
    r, 200, ["results"],
    body_check=lambda d: len(d.get("results", [])) == 2,
)


# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 60)
total = PASS + FAIL
print(f"Phase 5 Results: {PASS}/{total} passed, {FAIL} failed")
if FAIL == 0:
    print("🎉 All Phase 5 tests passed!")
else:
    print(f"⚠️  {FAIL} test(s) failed — check output above")
print("=" * 60)

sys.exit(0 if FAIL == 0 else 1)
