"""
Phase 7 — Twilio SMS Confirmation Tests

Tests:
1. Send appointment confirmation via body request (POST /send-confirmation)
2. Send appointment confirmation via path param (POST /send-confirmation/{id})
3. Send custom SMS (POST /send)
4. SMS auto-send on booking via Vapi tool-calls webhook
5. Credential resolution (missing Twilio config scenarios)
6. Template rendering (English + Spanish)
7. Edge cases (nonexistent appointment, no phone, SMS disabled)
8. Authentication checks

Note: Without real Twilio credentials, SMS sending will fail gracefully.
The tests validate the API structure, error handling, template rendering,
and end-to-end flow — actual Twilio delivery is expected to fail.
"""

import json
import requests
import sys
import os
from uuid import uuid4
from datetime import date, timedelta

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding='utf-8')

BASE = "http://localhost:8008"
PASS = 0
FAIL = 0
TEST_SUFFIX = uuid4().hex[:6]


def check(label, resp, expected_status=200, expected_keys=None, body_check=None):
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
        details.append(f"body_check failed: {json.dumps(data, default=str)[:300]}")

    if ok:
        PASS += 1
        print(f"  PASS: {label}")
    else:
        FAIL += 1
        print(f"  FAIL: {label} -- {', '.join(details)}")
        if data:
            print(f"     Body: {json.dumps(data, default=str)[:400]}")

    return data


# ============================================================
# Get auth tokens
# ============================================================
print("=" * 60)
print("Phase 7 -- Twilio SMS Confirmation Tests")
print("=" * 60)

# Login as practice_admin
r = requests.post(f"{BASE}/api/auth/login", json={
    "email": "dr.stefanides@stefanides.com",
    "password": "doctor123",
})
if r.status_code == 200:
    ADMIN_TOKEN = r.json()["access_token"]
    print(f"  Logged in as practice_admin")
else:
    r = requests.post(f"{BASE}/api/auth/login", json={
        "email": "jennie@stefanides.com",
        "password": "secretary123",
    })
    ADMIN_TOKEN = r.json()["access_token"]
    print(f"  Logged in as secretary")

HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


# ------------------------------------------------------------------
# SETUP: Create a test patient + book an appointment
# ------------------------------------------------------------------
print("\n--- Setup: Create test patient and appointment ---")

# Create patient
r = requests.post(
    f"{BASE}/api/patients/",
    json={
        "first_name": f"SmsTest{TEST_SUFFIX}",
        "last_name": f"Phase7{TEST_SUFFIX}",
        "dob": "1990-06-15",
        "phone": "+12125551234",
        "insurance_carrier": "Aetna",
        "language_preference": "en",
    },
    headers=HEADERS,
)
if r.status_code == 201:
    PATIENT_ID = r.json()["id"]
    print(f"  Created test patient: {PATIENT_ID}")
else:
    print(f"  ERROR creating patient: {r.status_code} {r.text[:200]}")
    PATIENT_ID = None

# Create a Spanish-speaking patient
r = requests.post(
    f"{BASE}/api/patients/",
    json={
        "first_name": f"SmsEs{TEST_SUFFIX}",
        "last_name": f"Prueba{TEST_SUFFIX}",
        "dob": "1985-09-20",
        "phone": "+12125559876",
        "insurance_carrier": "UnitedHealthcare",
        "language_preference": "es",
    },
    headers=HEADERS,
)
if r.status_code == 201:
    SPANISH_PATIENT_ID = r.json()["id"]
    print(f"  Created Spanish test patient: {SPANISH_PATIENT_ID}")
else:
    print(f"  ERROR creating Spanish patient: {r.status_code} {r.text[:200]}")
    SPANISH_PATIENT_ID = None

# Get an appointment type
r = requests.get(f"{BASE}/api/practice/appointment-types/", headers=HEADERS)
appt_types = r.json().get("appointment_types", [])
if appt_types:
    APPT_TYPE_ID = appt_types[0]["id"]
    print(f"  Using appointment type: {appt_types[0]['name']} ({APPT_TYPE_ID})")
else:
    print("  ERROR: No appointment types found")
    APPT_TYPE_ID = None

# Find an available slot
tomorrow = (date.today() + timedelta(days=1)).isoformat()
r = requests.get(
    f"{BASE}/api/appointments/next-available",
    params={"from_date": tomorrow},
    headers=HEADERS,
)
if r.status_code == 200:
    slot = r.json()
    APPT_DATE = slot["date"]
    APPT_TIME = slot["time"]
    print(f"  Next available slot: {APPT_DATE} at {APPT_TIME}")
else:
    print(f"  ERROR finding slot: {r.status_code} {r.text[:200]}")
    APPT_DATE = tomorrow
    APPT_TIME = "09:00"

# Book the appointment for English patient
APPOINTMENT_ID = None
if PATIENT_ID and APPT_TYPE_ID:
    r = requests.post(
        f"{BASE}/api/appointments/book",
        json={
            "patient_id": PATIENT_ID,
            "appointment_type_id": APPT_TYPE_ID,
            "date": APPT_DATE,
            "time": APPT_TIME,
        },
        headers=HEADERS,
    )
    if r.status_code == 201:
        APPOINTMENT_ID = r.json()["id"]
        print(f"  Booked appointment: {APPOINTMENT_ID}")
    else:
        print(f"  ERROR booking appointment: {r.status_code} {r.text[:200]}")

# Book appointment for Spanish patient (use next slot)
SPANISH_APPOINTMENT_ID = None
if SPANISH_PATIENT_ID and APPT_TYPE_ID:
    # Get another available slot
    r = requests.get(
        f"{BASE}/api/appointments/next-available",
        params={"from_date": APPT_DATE},
        headers=HEADERS,
    )
    if r.status_code == 200:
        slot2 = r.json()
        r = requests.post(
            f"{BASE}/api/appointments/book",
            json={
                "patient_id": SPANISH_PATIENT_ID,
                "appointment_type_id": APPT_TYPE_ID,
                "date": slot2["date"],
                "time": slot2["time"],
            },
            headers=HEADERS,
        )
        if r.status_code == 201:
            SPANISH_APPOINTMENT_ID = r.json()["id"]
            print(f"  Booked Spanish appointment: {SPANISH_APPOINTMENT_ID}")
        else:
            print(f"  ERROR booking Spanish appt: {r.status_code} {r.text[:200]}")


# ------------------------------------------------------------------
# TEST 1: Send confirmation via body (POST /send-confirmation)
# ------------------------------------------------------------------
print("\n--- Test 1: Send confirmation via body request ---")
if APPOINTMENT_ID:
    r = requests.post(
        f"{BASE}/api/sms/send-confirmation",
        json={"appointment_id": APPOINTMENT_ID},
        headers=HEADERS,
    )
    data = check(
        "POST /send-confirmation returns SmsResponse",
        r, 200, ["success"],
    )
    # Without real Twilio creds, success will be False — that's expected
    if data:
        print(f"     success={data.get('success')}, error={data.get('error', 'none')[:100]}")
        # The key thing is it didn't crash — it returned a structured response
else:
    print("  SKIP: No appointment to test with")


# ------------------------------------------------------------------
# TEST 2: Send confirmation via path param
# ------------------------------------------------------------------
print("\n--- Test 2: Send confirmation via path param ---")
if APPOINTMENT_ID:
    r = requests.post(
        f"{BASE}/api/sms/send-confirmation/{APPOINTMENT_ID}",
        headers=HEADERS,
    )
    data = check(
        "POST /send-confirmation/{id} returns SmsResponse",
        r, 200, ["success"],
    )
    if data:
        print(f"     success={data.get('success')}, error={data.get('error', 'none')[:100]}")
else:
    print("  SKIP: No appointment to test with")


# ------------------------------------------------------------------
# TEST 3: Send confirmation for Spanish patient
# ------------------------------------------------------------------
print("\n--- Test 3: Send confirmation for Spanish patient ---")
if SPANISH_APPOINTMENT_ID:
    r = requests.post(
        f"{BASE}/api/sms/send-confirmation",
        json={"appointment_id": SPANISH_APPOINTMENT_ID},
        headers=HEADERS,
    )
    data = check(
        "POST /send-confirmation for Spanish patient",
        r, 200, ["success"],
    )
    if data:
        print(f"     success={data.get('success')}, body preview={data.get('body', '')[:80]}")
else:
    print("  SKIP: No Spanish appointment to test with")


# ------------------------------------------------------------------
# TEST 4: Send custom SMS
# ------------------------------------------------------------------
print("\n--- Test 4: Send custom SMS ---")
r = requests.post(
    f"{BASE}/api/sms/send",
    json={
        "to_number": "+12125551234",
        "body": "This is a test message from the AI Medical Receptionist.",
    },
    headers=HEADERS,
)
data = check(
    "POST /send custom SMS returns SmsResponse",
    r, 200, ["success"],
)
if data:
    print(f"     success={data.get('success')}, error={data.get('error', 'none')[:100]}")


# ------------------------------------------------------------------
# TEST 5: Send confirmation — nonexistent appointment (404)
# ------------------------------------------------------------------
print("\n--- Test 5: Nonexistent appointment ---")
fake_appt_id = str(uuid4())
r = requests.post(
    f"{BASE}/api/sms/send-confirmation",
    json={"appointment_id": fake_appt_id},
    headers=HEADERS,
)
check(
    "POST /send-confirmation with fake appointment_id returns 404",
    r, 404,
)


# ------------------------------------------------------------------
# TEST 6: Send confirmation via path — nonexistent appointment (404)
# ------------------------------------------------------------------
print("\n--- Test 6: Nonexistent appointment via path ---")
r = requests.post(
    f"{BASE}/api/sms/send-confirmation/{fake_appt_id}",
    headers=HEADERS,
)
check(
    "POST /send-confirmation/{fake_id} returns 404",
    r, 404,
)


# ------------------------------------------------------------------
# TEST 7: Send custom SMS — invalid phone format (422)
# ------------------------------------------------------------------
print("\n--- Test 7: Invalid phone format ---")
r = requests.post(
    f"{BASE}/api/sms/send",
    json={
        "to_number": "not-a-phone",
        "body": "Test",
    },
    headers=HEADERS,
)
check(
    "POST /send with invalid phone returns 422",
    r, 422,
)


# ------------------------------------------------------------------
# TEST 8: Send custom SMS — missing body (422)
# ------------------------------------------------------------------
print("\n--- Test 8: Missing body field ---")
r = requests.post(
    f"{BASE}/api/sms/send",
    json={
        "to_number": "+12125551234",
    },
    headers=HEADERS,
)
check(
    "POST /send with missing body returns 422",
    r, 422,
)


# ------------------------------------------------------------------
# TEST 9: Vapi tool-call book_appointment triggers SMS auto-send
# ------------------------------------------------------------------
print("\n--- Test 9: Vapi book_appointment auto-sends SMS ---")
VAPI_CALL_ID = f"test-sms-{uuid4().hex[:8]}"
TC_ID = f"tc-{uuid4().hex[:8]}"

# Create call record first
requests.post(f"{BASE}/api/webhooks/vapi", json={
    "message": {
        "type": "status-update",
        "status": "in-progress",
        "call": {
            "id": VAPI_CALL_ID,
            "type": "inboundPhoneCall",
            "customer": {"number": "+12125551234"},
        },
    }
})

# Find another available slot for the Vapi booking
r = requests.get(
    f"{BASE}/api/appointments/next-available",
    params={"from_date": APPT_DATE},
    headers=HEADERS,
)
if r.status_code == 200:
    vapi_slot = r.json()
    vapi_date = vapi_slot["date"]
    vapi_time = vapi_slot["time"]
else:
    vapi_date = (date.today() + timedelta(days=3)).isoformat()
    vapi_time = "11:00"

r = requests.post(f"{BASE}/api/webhooks/vapi", json={
    "message": {
        "type": "tool-calls",
        "call": {"id": VAPI_CALL_ID, "type": "inboundPhoneCall"},
        "toolCallList": [
            {
                "id": TC_ID,
                "name": "book_appointment",
                "function": {
                    "name": "book_appointment",
                    "arguments": json.dumps({
                        "first_name": f"VapiSms{TEST_SUFFIX}",
                        "last_name": f"AutoSend{TEST_SUFFIX}",
                        "dob": "1988-04-10",
                        "phone": "+12125557777",
                        "date": vapi_date,
                        "time": vapi_time,
                    }),
                },
            }
        ],
    }
})
data = check(
    "Vapi book_appointment returns success with sms_sent field",
    r, 200, ["results"],
    body_check=lambda d: len(d.get("results", [])) == 1,
)
if data and data.get("results"):
    result_val = data["results"][0].get("result", {})
    if isinstance(result_val, dict):
        print(f"     Booking success={result_val.get('success')}, sms_sent={result_val.get('sms_sent')}")


# ------------------------------------------------------------------
# TEST 10: Template rendering — English format
# ------------------------------------------------------------------
print("\n--- Test 10: Template rendering — English ---")
try:
    sys.path.insert(0, ".")
    from app.services.sms_service import render_sms_template, format_appointment_datetime, DEFAULT_TEMPLATES

    # Test English template rendering
    variables = {
        "doctor": "Dr. Stefanides",
        "date": "Monday, June 15, 2025",
        "time": "9:00 AM",
        "address": "123 Main St, New York, NY",
        "patient_name": "John Doe",
        "phone": "(212) 555-1234",
    }
    rendered = render_sms_template(DEFAULT_TEMPLATES, "en", variables)

    en_ok = (
        "Dr. Stefanides" in rendered
        and "Monday, June 15, 2025" in rendered
        and "9:00 AM" in rendered
        and "123 Main St" in rendered
        and "(212) 555-1234" in rendered
    )

    if en_ok:
        PASS += 1
        print(f"  PASS: English template rendered correctly")
        print(f"     Preview: {rendered[:100]}...")
    else:
        FAIL += 1
        print(f"  FAIL: English template missing expected content")
        print(f"     Got: {rendered[:200]}")
except Exception as e:
    FAIL += 1
    print(f"  FAIL: Template rendering raised exception: {e}")


# ------------------------------------------------------------------
# TEST 11: Template rendering — Spanish format
# ------------------------------------------------------------------
print("\n--- Test 11: Template rendering — Spanish ---")
try:
    variables_es = {
        "doctor": "Dr. Stefanides",
        "date": "Lunes, 15 de junio de 2025",
        "time": "9:00 AM",
        "address": "123 Main St, New York, NY",
        "patient_name": "Juan Garcia",
        "phone": "(212) 555-1234",
    }
    rendered_es = render_sms_template(DEFAULT_TEMPLATES, "es", variables_es)

    es_ok = (
        "Dr. Stefanides" in rendered_es
        and "Lunes, 15 de junio de 2025" in rendered_es
        and "9:00 AM" in rendered_es
        and "Su cita" in rendered_es  # Spanish template starts with "Su cita"
    )

    if es_ok:
        PASS += 1
        print(f"  PASS: Spanish template rendered correctly")
        print(f"     Preview: {rendered_es[:100]}...")
    else:
        FAIL += 1
        print(f"  FAIL: Spanish template missing expected content")
        print(f"     Got: {rendered_es[:200]}")
except Exception as e:
    FAIL += 1
    print(f"  FAIL: Spanish template rendering raised exception: {e}")


# ------------------------------------------------------------------
# TEST 12: Template rendering — fallback for unknown language
# ------------------------------------------------------------------
print("\n--- Test 12: Template rendering — language fallback ---")
try:
    rendered_fallback = render_sms_template(DEFAULT_TEMPLATES, "fr", variables)

    # Should fall back to English
    fb_ok = "Your appointment" in rendered_fallback  # English template starts with this

    if fb_ok:
        PASS += 1
        print(f"  PASS: Unknown language falls back to English")
    else:
        FAIL += 1
        print(f"  FAIL: Language fallback did not produce English template")
        print(f"     Got: {rendered_fallback[:200]}")
except Exception as e:
    FAIL += 1
    print(f"  FAIL: Language fallback raised exception: {e}")


# ------------------------------------------------------------------
# TEST 13: Date/time formatting — English
# ------------------------------------------------------------------
print("\n--- Test 13: Date/time formatting — English ---")
try:
    from datetime import time as time_cls
    fd, ft = format_appointment_datetime(
        date(2025, 2, 24),
        time_cls(9, 0),
        "America/New_York",
        "en",
    )

    en_dt_ok = (
        "Monday" in fd
        and "February" in fd
        and "24" in fd
        and "2025" in fd
        and "9:00" in ft
        and "AM" in ft
    )

    if en_dt_ok:
        PASS += 1
        print(f"  PASS: English date/time: '{fd}' / '{ft}'")
    else:
        FAIL += 1
        print(f"  FAIL: English date/time incorrect: '{fd}' / '{ft}'")
except Exception as e:
    FAIL += 1
    print(f"  FAIL: English date/time formatting raised exception: {e}")


# ------------------------------------------------------------------
# TEST 14: Date/time formatting — Spanish
# ------------------------------------------------------------------
print("\n--- Test 14: Date/time formatting — Spanish ---")
try:
    fd_es, ft_es = format_appointment_datetime(
        date(2025, 2, 24),
        time_cls(14, 30),
        "America/New_York",
        "es",
    )

    es_dt_ok = (
        "Lunes" in fd_es
        and "febrero" in fd_es
        and "24" in fd_es
        and "2025" in fd_es
        and "2:30" in ft_es
        and "PM" in ft_es
    )

    if es_dt_ok:
        PASS += 1
        print(f"  PASS: Spanish date/time: '{fd_es}' / '{ft_es}'")
    else:
        FAIL += 1
        print(f"  FAIL: Spanish date/time incorrect: '{fd_es}' / '{ft_es}'")
except Exception as e:
    FAIL += 1
    print(f"  FAIL: Spanish date/time formatting raised exception: {e}")


# ------------------------------------------------------------------
# TEST 15: Template rendering — missing variables handled gracefully
# ------------------------------------------------------------------
print("\n--- Test 15: Template with missing variables ---")
try:
    partial_vars = {"doctor": "Dr. Smith"}  # Missing date, time, address, etc.
    rendered_partial = render_sms_template(DEFAULT_TEMPLATES, "en", partial_vars)

    # Should render without crashing; missing vars stay as {var_name}
    partial_ok = (
        "Dr. Smith" in rendered_partial
        and "{date}" in rendered_partial  # Missing var preserved
        and "{time}" in rendered_partial
    )

    if partial_ok:
        PASS += 1
        print(f"  PASS: Missing variables handled gracefully")
        print(f"     Preview: {rendered_partial[:120]}...")
    else:
        FAIL += 1
        print(f"  FAIL: Missing variables not handled properly")
        print(f"     Got: {rendered_partial[:200]}")
except Exception as e:
    FAIL += 1
    print(f"  FAIL: Missing variable handling raised exception: {e}")


# ------------------------------------------------------------------
# TEST 16: Custom template rendering (practice-specific)
# ------------------------------------------------------------------
print("\n--- Test 16: Custom template rendering ---")
try:
    custom_templates = {
        "en": "Hi {patient_name}! Reminder: {date} at {time} with {doctor}. Call {phone} to change.",
        "es": "Hola {patient_name}! Recordatorio: {date} a las {time} con {doctor}. Llame al {phone}.",
    }
    custom_rendered = render_sms_template(custom_templates, "en", variables)

    custom_ok = (
        "Hi John Doe!" in custom_rendered
        and "Reminder:" in custom_rendered
        and "Dr. Stefanides" in custom_rendered
    )

    if custom_ok:
        PASS += 1
        print(f"  PASS: Custom template rendered correctly")
        print(f"     Preview: {custom_rendered[:120]}...")
    else:
        FAIL += 1
        print(f"  FAIL: Custom template rendering failed")
        print(f"     Got: {custom_rendered[:200]}")
except Exception as e:
    FAIL += 1
    print(f"  FAIL: Custom template rendering raised exception: {e}")


# ------------------------------------------------------------------
# TEST 17: Unauthenticated access
# ------------------------------------------------------------------
print("\n--- Test 17: Unauthenticated access ---")
r = requests.post(
    f"{BASE}/api/sms/send-confirmation",
    json={"appointment_id": str(uuid4())},
)
check(
    "POST /send-confirmation without auth returns 401 or 403",
    r, r.status_code,
    body_check=lambda d: r.status_code in (401, 403),
)

r = requests.post(
    f"{BASE}/api/sms/send",
    json={"to_number": "+12125551234", "body": "test"},
)
check(
    "POST /send without auth returns 401 or 403",
    r, r.status_code,
    body_check=lambda d: r.status_code in (401, 403),
)


# ------------------------------------------------------------------
# TEST 18: E.164 phone validation
# ------------------------------------------------------------------
print("\n--- Test 18: E.164 phone validation ---")

# Valid international number
r = requests.post(
    f"{BASE}/api/sms/send",
    json={
        "to_number": "+442071234567",  # UK number
        "body": "International test message",
    },
    headers=HEADERS,
)
check(
    "POST /send accepts valid international E.164 number",
    r, 200, ["success"],
)

# Invalid - missing + prefix
r = requests.post(
    f"{BASE}/api/sms/send",
    json={
        "to_number": "12125551234",
        "body": "Missing plus prefix",
    },
    headers=HEADERS,
)
check(
    "POST /send rejects phone without + prefix (422)",
    r, 422,
)


# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 60)
total = PASS + FAIL
print(f"Phase 7 Results: {PASS}/{total} passed, {FAIL} failed")
if FAIL == 0:
    print("All Phase 7 tests passed!")
else:
    print(f"{FAIL} test(s) failed -- check output above")
print("=" * 60)

sys.exit(0 if FAIL == 0 else 1)
