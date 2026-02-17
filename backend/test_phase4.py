"""Phase 4 comprehensive test script."""
import requests
from datetime import date, timedelta

BASE = "http://localhost:8003"

# Login as practice_admin (dr.stefanides)
r = requests.post(f"{BASE}/api/auth/login", json={"email": "dr.stefanides@stefanides.com", "password": "doctor123"})
token = r.json()["access_token"]
H = {"Authorization": f"Bearer {token}"}
print("LOGIN: OK (practice_admin)")

# ===== PATIENT TESTS =====
print("\n===== PATIENT TESTS =====")

# 1. Create patient
r = requests.post(f"{BASE}/api/patients/", json={
    "first_name": "Maria",
    "last_name": "Rodriguez",
    "dob": "1985-03-15",
    "phone": "718-555-0123",
    "address": "123 Main St, Brooklyn, NY 11201",
    "insurance_carrier": "Fidelis Care",
    "member_id": "FC123456",
    "language_preference": "es"
}, headers=H)
print(f"1. CREATE patient: {r.status_code}")
if r.status_code == 201:
    patient = r.json()
    patient_id = patient["id"]
    print(f"   id={patient_id}")
    print(f"   name={patient['first_name']} {patient['last_name']}")
    print(f"   is_new={patient['is_new']}")
else:
    print(f"   ERROR: {r.text[:200]}")
    exit(1)

# 2. Create second patient
r = requests.post(f"{BASE}/api/patients/", json={
    "first_name": "John",
    "last_name": "Smith",
    "dob": "1970-08-20",
    "phone": "212-555-0456",
    "insurance_carrier": "Medicare",
    "accident_type": "workers_comp",
    "accident_date": "2026-01-10"
}, headers=H)
print(f"2. CREATE patient 2: {r.status_code}")
patient2_id = r.json()["id"] if r.status_code == 201 else None

# 3. List patients
r = requests.get(f"{BASE}/api/patients/", headers=H)
print(f"3. LIST patients: {r.status_code} (total={r.json()['total']})")

# 4. Search by name
r = requests.get(f"{BASE}/api/patients/search?first_name=Maria", headers=H)
print(f"4. SEARCH by name: {r.status_code} (found={r.json()['total']})")

# 5. Search by phone
r = requests.get(f"{BASE}/api/patients/?search=718", headers=H)
print(f"5. SEARCH by phone: {r.status_code} (found={r.json()['total']})")

# 6. Get patient by ID
r = requests.get(f"{BASE}/api/patients/{patient_id}", headers=H)
print(f"6. GET patient: {r.status_code} ({r.json()['first_name']} {r.json()['last_name']})")

# 7. Update patient
r = requests.put(f"{BASE}/api/patients/{patient_id}", json={
    "phone": "718-555-9999",
    "notes": "Prefers afternoon appointments"
}, headers=H)
print(f"7. UPDATE patient: {r.status_code} (phone={r.json()['phone']})")

print("\n===== APPOINTMENT TESTS =====")

# Get appointment types for booking
r = requests.get(f"{BASE}/api/practice/appointment-types/", headers=H)
appt_types = r.json()["appointment_types"]
first_type_id = appt_types[0]["id"]
print(f"Using type: {appt_types[0]['name']} (id={first_type_id})")

# 8. Find next available slot
r = requests.get(f"{BASE}/api/appointments/next-available", headers=H)
print(f"8. NEXT AVAILABLE: {r.status_code}")
if r.status_code == 200:
    slot = r.json()
    print(f"   date={slot['date']}, time={slot['time']}")
    book_date = slot["date"]
    book_time = slot["time"]
else:
    print(f"   ERROR: {r.text[:200]}")
    today = date.today()
    days_ahead = 0 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    next_monday = today + timedelta(days=days_ahead)
    book_date = next_monday.isoformat()
    book_time = "09:00:00"

# 9. Book appointment
r = requests.post(f"{BASE}/api/appointments/book", json={
    "patient_id": patient_id,
    "appointment_type_id": first_type_id,
    "date": book_date,
    "time": book_time,
    "booked_by": "ai",
    "notes": "New patient - needs full intake"
}, headers=H)
print(f"9. BOOK appointment: {r.status_code}")
if r.status_code == 201:
    appt = r.json()
    appt_id = appt["id"]
    print(f"   id={appt_id}")
    print(f"   patient_name={appt['patient_name']}")
    print(f"   type={appt['appointment_type_name']}")
    print(f"   date={appt['date']} time={appt['time']}")
    print(f"   status={appt['status']}")
else:
    print(f"   ERROR: {r.text[:300]}")
    exit(1)

# Check patient is_new was flipped
r = requests.get(f"{BASE}/api/patients/{patient_id}", headers=H)
print(f"   patient is_new after booking: {r.json()['is_new']}")

# 10. List appointments
r = requests.get(f"{BASE}/api/appointments/", headers=H)
print(f"10. LIST appointments: {r.status_code} (total={r.json()['total']})")

# 11. Get appointment by ID
r = requests.get(f"{BASE}/api/appointments/{appt_id}", headers=H)
print(f"11. GET appointment: {r.status_code} (status={r.json()['status']})")

# 12. Confirm appointment
r = requests.put(f"{BASE}/api/appointments/{appt_id}/confirm", headers=H)
print(f"12. CONFIRM appointment: {r.status_code} (status={r.json()['status']})")

# 13. Book second appointment for rescheduling test
r = requests.get(f"{BASE}/api/appointments/next-available?preferred_time=14:00", headers=H)
if r.status_code == 200:
    slot2 = r.json()
else:
    slot2 = {"date": book_date, "time": "09:15:00"}

r = requests.post(f"{BASE}/api/appointments/book", json={
    "patient_id": patient2_id if patient2_id else patient_id,
    "appointment_type_id": first_type_id,
    "date": slot2["date"],
    "time": slot2["time"],
}, headers=H)
print(f"13. BOOK for reschedule: {r.status_code}")
if r.status_code == 201:
    appt2_id = r.json()["id"]
else:
    print(f"    ERROR: {r.text[:200]}")
    appt2_id = None

if appt2_id:
    # 14. Reschedule appointment
    r = requests.get(f"{BASE}/api/appointments/next-available?preferred_time=10:00", headers=H)
    if r.status_code == 200:
        new_slot = r.json()
        r = requests.put(f"{BASE}/api/appointments/{appt2_id}/reschedule", json={
            "new_date": new_slot["date"],
            "new_time": new_slot["time"],
            "notes": "Patient requested morning slot"
        }, headers=H)
        print(f"14. RESCHEDULE: {r.status_code}")
        if r.status_code == 200:
            new_appt = r.json()
            print(f"    new date={new_appt['date']} time={new_appt['time']}")
            appt3_id = new_appt["id"]

            # 15. Cancel the rescheduled appointment
            r = requests.put(f"{BASE}/api/appointments/{appt3_id}/cancel", json={
                "reason": "Patient called to cancel"
            }, headers=H)
            print(f"15. CANCEL: {r.status_code} (status={r.json()['status']})")
        else:
            print(f"    ERROR: {r.text[:200]}")

# 16. Try double-booking same slot (overbooking=True, max=3, should succeed)
r = requests.post(f"{BASE}/api/appointments/book", json={
    "patient_id": patient_id,
    "appointment_type_id": first_type_id,
    "date": book_date,
    "time": book_time,
}, headers=H)
print(f"16. DOUBLE-BOOK test: {r.status_code} (overbooking=True, max=3)")

# 17. List with filters
r = requests.get(f"{BASE}/api/appointments/?status=booked", headers=H)
print(f"17. LIST booked only: {r.status_code} (total={r.json()['total']})")

r = requests.get(f"{BASE}/api/appointments/?status=cancelled", headers=H)
print(f"    LIST cancelled: {r.status_code} (total={r.json()['total']})")

# 18. Secretary RBAC
sec_r = requests.post(f"{BASE}/api/auth/login", json={"email": "jennie@stefanides.com", "password": "secretary123"})
sec_token = sec_r.json()["access_token"]
sec_H = {"Authorization": f"Bearer {sec_token}"}

r = requests.get(f"{BASE}/api/patients/", headers=sec_H)
print(f"\n18. RBAC - Secretary LIST patients: {r.status_code} (expected 200)")

r = requests.get(f"{BASE}/api/appointments/", headers=sec_H)
print(f"    RBAC - Secretary LIST appointments: {r.status_code} (expected 200)")

print("\n=== ALL PHASE 4 TESTS COMPLETE ===")
