"""
Phase 6 — Stedi Insurance Verification Tests

Tests:
1. Carrier lookup (fuzzy matching)
2. Insurance verification via REST API (will fail gracefully without Stedi key)
3. Verification history (list + get)
4. Vapi tool-calls with verify_insurance (real Stedi integration)
5. Edge cases (unknown carrier, missing fields)
"""

import json
import requests
import sys
import os
from uuid import uuid4

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding='utf-8')

BASE = "http://localhost:8007"
PASS = 0
FAIL = 0


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
print("Phase 6 -- Stedi Insurance Verification Tests")
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
    # Try secretary
    r = requests.post(f"{BASE}/api/auth/login", json={
        "email": "jennie@stefanides.com",
        "password": "secretary123",
    })
    ADMIN_TOKEN = r.json()["access_token"]
    print(f"  Logged in as secretary")

HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


# ------------------------------------------------------------------
# TEST 1: Carrier lookup — existing carrier (exact match)
# ------------------------------------------------------------------
print("\n--- Test 1: Carrier lookup — exact match ---")

# First, let's see what carriers exist
r = requests.get(f"{BASE}/api/practice/insurance-carriers/", headers=HEADERS)
carriers_data = r.json()
carriers = carriers_data.get("carriers", [])
print(f"     Found {len(carriers)} carriers in practice")

if carriers:
    carrier_name = carriers[0]["name"]
    payer_id = carriers[0].get("stedi_payer_id")
    print(f"     Testing with carrier: '{carrier_name}' (payer_id={payer_id})")

    r = requests.get(
        f"{BASE}/api/insurance/lookup-carrier",
        params={"carrier_name": carrier_name},
        headers=HEADERS,
    )
    data = check(
        f"lookup-carrier exact match '{carrier_name}'",
        r, 200, ["found"],
    )
    if data.get("found"):
        print(f"     Resolved: {data.get('carrier_name')} -> {data.get('payer_id')}")
else:
    print("  SKIP: No carriers configured -- creating test carriers first")

    # Create test carriers
    for carrier_info in [
        {"name": "Aetna", "aliases": ["Aetna Health", "Aetna Better Health"], "stedi_payer_id": "60054"},
        {"name": "UnitedHealthcare", "aliases": ["United", "UHC", "United Health"], "stedi_payer_id": "87726"},
        {"name": "MetroPlus", "aliases": ["Metro Plus", "MetroPlus Health"], "stedi_payer_id": "MPLUS"},
        {"name": "Fidelis Care", "aliases": ["Fidelis", "Fidelis NY"], "stedi_payer_id": "FIDEL"},
    ]:
        requests.post(
            f"{BASE}/api/practice/insurance-carriers/",
            json=carrier_info,
            headers=HEADERS,
        )
    print("     Created 4 test carriers")

    r = requests.get(
        f"{BASE}/api/insurance/lookup-carrier",
        params={"carrier_name": "Aetna"},
        headers=HEADERS,
    )
    data = check(
        "lookup-carrier exact match 'Aetna'",
        r, 200, ["found"],
    )
    if data.get("found"):
        print(f"     Resolved: {data.get('carrier_name')} -> {data.get('payer_id')}")


# ------------------------------------------------------------------
# TEST 2: Carrier lookup — alias match
# ------------------------------------------------------------------
print("\n--- Test 2: Carrier lookup — alias match ---")
r = requests.get(
    f"{BASE}/api/insurance/lookup-carrier",
    params={"carrier_name": "UHC"},
    headers=HEADERS,
)
data = check("lookup-carrier alias match 'UHC'", r, 200, ["found"])
if data.get("found"):
    print(f"     Resolved: {data.get('carrier_name')} -> {data.get('payer_id')}")


# ------------------------------------------------------------------
# TEST 3: Carrier lookup — partial match
# ------------------------------------------------------------------
print("\n--- Test 3: Carrier lookup — partial match ---")
r = requests.get(
    f"{BASE}/api/insurance/lookup-carrier",
    params={"carrier_name": "United"},
    headers=HEADERS,
)
data = check("lookup-carrier partial match 'United'", r, 200, ["found"])
if data.get("found"):
    print(f"     Resolved: {data.get('carrier_name')} -> {data.get('payer_id')}")


# ------------------------------------------------------------------
# TEST 4: Carrier lookup — not found
# ------------------------------------------------------------------
print("\n--- Test 4: Carrier lookup — unknown carrier ---")
r = requests.get(
    f"{BASE}/api/insurance/lookup-carrier",
    params={"carrier_name": "NonexistentInsuranceCo12345"},
    headers=HEADERS,
)
data = check(
    "lookup-carrier unknown returns found=false",
    r, 200,
    body_check=lambda d: d.get("found") == False,
)


# ------------------------------------------------------------------
# TEST 5: Verify insurance via REST API (will fail gracefully without Stedi key)
# ------------------------------------------------------------------
print("\n--- Test 5: Verify insurance via REST API ---")

# First ensure we have a patient
r = requests.get(
    f"{BASE}/api/patients/search",
    params={"first_name": "Test", "last_name": "Phase5New"},
    headers=HEADERS,
)
patients = r.json().get("patients", [])

# Always create a fresh test patient for insurance tests
r = requests.post(
    f"{BASE}/api/patients/",
    json={
        "first_name": "InsTest",
        "last_name": "Phase6",
        "dob": "1985-03-15",
        "phone": "+12125559876",
        "insurance_carrier": "Aetna",
        "member_id": "INS12345",
    },
    headers=HEADERS,
)
if r.status_code == 201:
    patient_id = r.json()["id"]
    print(f"     Created test patient: {patient_id}")
elif patients:
    patient_id = patients[0]["id"]
    print(f"     Using existing patient: {patient_id}")
else:
    print(f"     ERROR creating patient: {r.status_code} {r.text[:200]}")
    patient_id = None

r = requests.post(
    f"{BASE}/api/insurance/verify",
    json={
        "patient_id": patient_id,
        "carrier_name": "Aetna",
        "member_id": "INS12345",
    },
    headers=HEADERS,
)
data = check(
    "POST /verify with valid patient",
    r, 200, ["id", "status", "carrier_name"],
)
if data:
    print(f"     Status: {data.get('status')}, Active: {data.get('is_active')}, Message: {data.get('message', '')[:100]}")


# ------------------------------------------------------------------
# TEST 6: Verify insurance by name+dob (no patient_id)
# ------------------------------------------------------------------
print("\n--- Test 6: Verify insurance by name+dob ---")
r = requests.post(
    f"{BASE}/api/insurance/verify",
    json={
        "carrier_name": "Aetna",
        "member_id": "INS12345",
        "first_name": "InsTest",
        "last_name": "Phase6",
        "date_of_birth": "1985-03-15",
    },
    headers=HEADERS,
)
data = check("POST /verify with name+dob lookup", r, 200, ["id", "status"])
if data:
    print(f"     Status: {data.get('status')}, Active: {data.get('is_active')}")


# ------------------------------------------------------------------
# TEST 7: Verify insurance — patient not found
# ------------------------------------------------------------------
print("\n--- Test 7: Verify insurance — patient not found ---")
r = requests.post(
    f"{BASE}/api/insurance/verify",
    json={
        "carrier_name": "Aetna",
        "member_id": "FAKE123",
        "first_name": "NoSuchPerson",
        "last_name": "DoesNotExist",
        "date_of_birth": "2000-01-01",
    },
    headers=HEADERS,
)
check("POST /verify with nonexistent patient returns 404", r, 404)


# ------------------------------------------------------------------
# TEST 8: Verify insurance — missing required fields
# ------------------------------------------------------------------
print("\n--- Test 8: Verify insurance — missing fields ---")
r = requests.post(
    f"{BASE}/api/insurance/verify",
    json={
        "carrier_name": "Aetna",
        "member_id": "INS12345",
        # no patient_id, no first_name/last_name/dob
    },
    headers=HEADERS,
)
check("POST /verify with missing patient info returns 400", r, 400)


# ------------------------------------------------------------------
# TEST 9: List verification history
# ------------------------------------------------------------------
print("\n--- Test 9: List verification history ---")
r = requests.get(f"{BASE}/api/insurance/", headers=HEADERS)
data = check(
    "GET /insurance/ returns list",
    r, 200, ["verifications", "total"],
)
if data:
    print(f"     Total verifications: {data.get('total')}")


# ------------------------------------------------------------------
# TEST 10: List verification history with patient filter
# ------------------------------------------------------------------
print("\n--- Test 10: List verifications filtered by patient ---")
r = requests.get(
    f"{BASE}/api/insurance/",
    params={"patient_id": patient_id},
    headers=HEADERS,
)
data = check(
    "GET /insurance/?patient_id= filtered list",
    r, 200, ["verifications", "total"],
)


# ------------------------------------------------------------------
# TEST 11: Get single verification by ID
# ------------------------------------------------------------------
print("\n--- Test 11: Get single verification ---")
# Get a verification ID from the list
r = requests.get(f"{BASE}/api/insurance/", headers=HEADERS)
verifications = r.json().get("verifications", [])
if verifications:
    v_id = verifications[0]["id"]
    r = requests.get(f"{BASE}/api/insurance/{v_id}", headers=HEADERS)
    check(
        f"GET /insurance/{{id}} returns verification",
        r, 200, ["id", "status", "carrier_name"],
    )
else:
    print("  SKIP: No verifications to fetch")


# ------------------------------------------------------------------
# TEST 12: Get nonexistent verification
# ------------------------------------------------------------------
print("\n--- Test 12: Get nonexistent verification ---")
fake_id = str(uuid4())
r = requests.get(f"{BASE}/api/insurance/{fake_id}", headers=HEADERS)
check("GET /insurance/{{fake_id}} returns 404", r, 404)


# ------------------------------------------------------------------
# TEST 13: Vapi tool-calls — verify_insurance (via webhook)
# ------------------------------------------------------------------
print("\n--- Test 13: Vapi tool-calls — verify_insurance ---")
VAPI_CALL_ID = f"test-ins-{uuid4().hex[:8]}"
TC_ID = f"tc-{uuid4().hex[:8]}"

# Create call record first
requests.post(f"{BASE}/api/webhooks/vapi", json={
    "message": {
        "type": "status-update",
        "status": "in-progress",
        "call": {
            "id": VAPI_CALL_ID,
            "type": "inboundPhoneCall",
            "customer": {"number": "+12125559876"},
        },
    }
})

r = requests.post(f"{BASE}/api/webhooks/vapi", json={
    "message": {
        "type": "tool-calls",
        "call": {"id": VAPI_CALL_ID, "type": "inboundPhoneCall"},
        "toolCallList": [
            {
                "id": TC_ID,
                "name": "verify_insurance",
                "function": {
                    "name": "verify_insurance",
                    "arguments": json.dumps({
                        "first_name": "InsTest",
                        "last_name": "Phase6",
                        "dob": "1985-03-15",
                        "insurance_carrier": "Aetna",
                        "member_id": "INS12345",
                    }),
                },
            }
        ],
    }
})
data = check(
    "Vapi tool-calls verify_insurance returns results",
    r, 200, ["results"],
    body_check=lambda d: len(d.get("results", [])) == 1,
)
if data.get("results"):
    result_val = data["results"][0].get("result", {})
    if isinstance(result_val, dict):
        print(f"     Verified: {result_val.get('verified')}, Message: {result_val.get('message', '')[:100]}")


# ------------------------------------------------------------------
# TEST 14: Vapi verify_insurance — unknown carrier
# ------------------------------------------------------------------
print("\n--- Test 14: Vapi verify_insurance — unknown carrier ---")
TC_ID_2 = f"tc-{uuid4().hex[:8]}"
r = requests.post(f"{BASE}/api/webhooks/vapi", json={
    "message": {
        "type": "tool-calls",
        "call": {"id": VAPI_CALL_ID, "type": "inboundPhoneCall"},
        "toolCallList": [
            {
                "id": TC_ID_2,
                "name": "verify_insurance",
                "function": {
                    "name": "verify_insurance",
                    "arguments": json.dumps({
                        "first_name": "InsTest",
                        "last_name": "Phase6",
                        "dob": "1985-03-15",
                        "insurance_carrier": "TotallyFakeInsurance",
                        "member_id": "FAKE999",
                    }),
                },
            }
        ],
    }
})
data = check(
    "Vapi verify_insurance unknown carrier returns graceful result",
    r, 200, ["results"],
    body_check=lambda d: len(d.get("results", [])) == 1,
)


# ------------------------------------------------------------------
# TEST 15: Unauthenticated access to REST endpoints
# ------------------------------------------------------------------
print("\n--- Test 15: Unauthenticated access ---")
r = requests.get(f"{BASE}/api/insurance/")
check("GET /insurance/ without auth returns 401 or 403", r, r.status_code,
      body_check=lambda d: r.status_code in (401, 403))

r = requests.post(f"{BASE}/api/insurance/verify", json={
    "carrier_name": "Aetna", "member_id": "123",
})
check("POST /verify without auth returns 401 or 403", r, r.status_code,
      body_check=lambda d: r.status_code in (401, 403))


# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 60)
total = PASS + FAIL
print(f"Phase 6 Results: {PASS}/{total} passed, {FAIL} failed")
if FAIL == 0:
    print("All Phase 6 tests passed!")
else:
    print(f"{FAIL} test(s) failed -- check output above")
print("=" * 60)

sys.exit(0 if FAIL == 0 else 1)
