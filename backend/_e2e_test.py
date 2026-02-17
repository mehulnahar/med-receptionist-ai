import sys, os, json, traceback
os.environ['PYTHONIOENCODING'] = 'utf-8'
import requests
from datetime import date, timedelta

BASE = 'http://localhost:8001/api'
bugs = []
passed = 0
failed = 0

def test(name, condition, detail='', response=None):
    global passed, failed
    if condition:
        passed += 1
        print(f'[PASS] {name}' + (f' - {detail}' if detail else ''))
    else:
        failed += 1
        err_detail = detail
        if response is not None:
            try:
                err_detail += f' | Response: {response.text[:300]}'
            except:
                pass
        bugs.append(f'{name}: {err_detail}')
        print(f'[FAIL] {name} - {err_detail}')

print('='*70)
print('  END-TO-END API TEST SUITE')
print('='*70)

print()
print('--- 1. AUTH TESTS ---')

r = requests.post(f'{BASE}/auth/login', json={'email': 'admin@mindcrew.tech', 'password': 'admin123'})
test('Admin login', r.status_code == 200, f'status={r.status_code}', r)
admin_token = r.json().get('access_token', '') if r.status_code == 200 else ''
admin_h = {'Authorization': f'Bearer {admin_token}'}

r = requests.post(f'{BASE}/auth/login', json={'email': 'jennie@stefanides.com', 'password': 'jennie123'})
test('Secretary login', r.status_code == 200, f'status={r.status_code}', r)
jennie_token = r.json().get('access_token', '') if r.status_code == 200 else ''
jennie_h = {'Authorization': f'Bearer {jennie_token}'}

r = requests.post(f'{BASE}/auth/login', json={'email': 'dr.stefanides@stefanides.com', 'password': 'doctor123'})
test('Practice admin login', r.status_code == 200, f'status={r.status_code}', r)
doc_token = r.json().get('access_token', '') if r.status_code == 200 else ''
doc_h = {'Authorization': f'Bearer {doc_token}'}

r = requests.post(f'{BASE}/auth/login', json={'email': 'admin@mindcrew.tech', 'password': 'wrongpassword'})
test('Bad password rejected', r.status_code == 401, f'status={r.status_code}', r)

r = requests.get(f'{BASE}/auth/me', headers=jennie_h)
test('GET /auth/me', r.status_code == 200 and r.json().get('email') == 'jennie@stefanides.com', f'status={r.status_code}', r)

r = requests.get(f'{BASE}/auth/me')
test('No token returns 401/403', r.status_code in [401, 403], f'status={r.status_code}', r)

r = requests.get(f'{BASE}/admin/practices', headers=jennie_h)
test('RBAC: Secretary blocked from admin', r.status_code == 403, f'status={r.status_code}', r)

r = requests.get(f'{BASE}/practice/users', headers=jennie_h)
test('RBAC: Secretary blocked from practice user mgmt', r.status_code == 403, f'status={r.status_code}', r)

print()
print('--- 2. ADMIN ENDPOINTS ---')

r = requests.get(f'{BASE}/admin/practices', headers=admin_h)
test('List practices', r.status_code == 200, f'{r.json().get("total",0)} practices', r)
practice_id = r.json()['practices'][0]['id'] if r.status_code == 200 and r.json().get('practices') else ''

r = requests.get(f'{BASE}/admin/practices/{practice_id}', headers=admin_h)
test('Get practice by ID', r.status_code == 200, r.json().get('name', ''), r)

r = requests.put(f'{BASE}/admin/practices/{practice_id}', headers=admin_h, json={'phone': '555-123-4567'})
test('Update practice', r.status_code == 200, f'phone={r.json().get("phone","")}', r)

r = requests.get(f'{BASE}/admin/users', headers=admin_h)
test('List users', r.status_code == 200, f'{r.json().get("total",0)} users', r)

r = requests.get(f'{BASE}/admin/users', headers=admin_h, params={'role': 'secretary'})
test('Filter users by role', r.status_code == 200, f'{r.json().get("total",0)} secretaries', r)

r = requests.get(f'{BASE}/admin/practices/{practice_id}/config', headers=admin_h)
test('Get practice config (admin)', r.status_code == 200, f'model={r.json().get("vapi_model_name","")}', r)

r = requests.put(f'{BASE}/admin/practices/{practice_id}/config', headers=admin_h, json={'vapi_model_name': 'gpt-4o-mini'})
test('Update practice config (admin)', r.status_code == 200, r)

r = requests.post(f'{BASE}/admin/practices', headers=admin_h, json={'name': 'Test Practice', 'slug': 'test-practice-e2e'})
if r.status_code == 201:
    test('Create practice', True, f'id={r.json().get("id","")}')
    test_practice_id = r.json()['id']
    r2 = requests.post(f'{BASE}/admin/practices', headers=admin_h, json={'name': 'Test Practice 2', 'slug': 'test-practice-e2e'})
    test('Duplicate slug rejected', r2.status_code == 400, f'status={r2.status_code}', r2)
else:
    test('Create practice', r.status_code == 201, f'status={r.status_code}', r)

print()
print('--- 3. PRACTICE ENDPOINTS ---')

r = requests.get(f'{BASE}/practice/settings', headers=jennie_h)
test('GET /practice/settings', r.status_code == 200, r.json().get('name', ''), r)

r = requests.get(f'{BASE}/practice/config/', headers=jennie_h)
test('GET /practice/config', r.status_code == 200, f'languages={r.json().get("languages",[])}', r)

r = requests.get(f'{BASE}/practice/schedule/', headers=jennie_h)
test('GET /practice/schedule', r.status_code == 200 and isinstance(r.json(), list), f'{len(r.json())} templates', r)

r = requests.get(f'{BASE}/practice/appointment-types/', headers=jennie_h)
test('GET /practice/appointment-types', r.status_code == 200, f'{len(r.json())} types', r)
appt_types_resp = r.json() if r.status_code == 200 else {}
appt_types = appt_types_resp.get('appointment_types', []) if isinstance(appt_types_resp, dict) else appt_types_resp

r = requests.get(f'{BASE}/practice/insurance-carriers/', headers=jennie_h)
test('GET /practice/insurance-carriers', r.status_code == 200, f'{len(r.json())} carriers', r)

r = requests.put(f'{BASE}/practice/settings', headers=doc_h, json={'phone': '555-999-0000'})
test('PUT /practice/settings (practice admin)', r.status_code == 200, r)

r = requests.put(f'{BASE}/practice/settings', headers=jennie_h, json={'phone': '555-111-2222'})
test('Secretary blocked from updating practice', r.status_code == 403, f'status={r.status_code}', r)

r = requests.put(f'{BASE}/practice/config/', headers=doc_h, json={'slot_duration_minutes': 15})
test('PUT /practice/config (practice admin)', r.status_code == 200, r)

print()
print('--- 4. PATIENT TESTS ---')

r = requests.get(f'{BASE}/patients/', headers=jennie_h)
test('List patients', r.status_code == 200, f'{r.json().get("total",0)} patients', r)

r = requests.get(f'{BASE}/patients/search', headers=jennie_h, params={'first_name': 'J'})
test('Search patients by first name', r.status_code == 200, f'{r.json().get("total",0)} found', r)

r = requests.get(f'{BASE}/patients/search', headers=jennie_h)
test('Search with no params rejected', r.status_code == 400, f'status={r.status_code}', r)

r = requests.post(f'{BASE}/patients/', headers=jennie_h, json={
    'first_name': 'E2E_Test',
    'last_name': 'Patient',
    'dob': '1990-05-15',
    'phone': '555-E2E-0001',
    'sex': 'male',
})
test('Create patient', r.status_code == 201, r)
test_patient_id = r.json().get('id', '') if r.status_code == 201 else ''

if test_patient_id:
    r = requests.get(f'{BASE}/patients/{test_patient_id}', headers=jennie_h)
    test('Get patient by ID', r.status_code == 200 and r.json().get('first_name') == 'E2E_Test', r)

if test_patient_id:
    r = requests.put(f'{BASE}/patients/{test_patient_id}', headers=jennie_h, json={'phone': '555-E2E-9999'})
    test('Update patient', r.status_code == 200 and r.json().get('phone') == '555-E2E-9999', r)

r = requests.get(f'{BASE}/patients/search', headers=jennie_h, params={'first_name': 'E2E_Test', 'last_name': 'Patient'})
test('Search finds created patient', r.status_code == 200 and r.json().get('total', 0) >= 1, f'total={r.json().get("total",0)}', r)

print()
print('--- 5. APPOINTMENT TESTS ---')

r = requests.get(f'{BASE}/appointments/', headers=jennie_h)
test('List appointments', r.status_code == 200, f'{r.json().get("total",0)} appointments', r)

appt_type_id = appt_types[0]['id'] if appt_types else None
tomorrow = (date.today() + timedelta(days=1)).isoformat()
book_body = {
    'patient_id': test_patient_id,
    'appointment_type_id': str(appt_type_id) if appt_type_id else '',
    'date': tomorrow,
    'time': '10:00',
    'notes': 'E2E test appointment',
    'booked_by': 'e2e_test',
}
if test_patient_id and appt_type_id:
    r = requests.post(f'{BASE}/appointments/book', headers=jennie_h, json=book_body)
    test('Book appointment', r.status_code == 201, f'status={r.status_code}', r)
    booked_appt_id = r.json().get('id', '') if r.status_code == 201 else ''

    if booked_appt_id:
        r = requests.get(f'{BASE}/appointments/{booked_appt_id}', headers=jennie_h)
        test('Get appointment by ID', r.status_code == 200 and r.json().get('status') == 'booked', r)

        r = requests.put(f'{BASE}/appointments/{booked_appt_id}/confirm', headers=jennie_h)
        test('Confirm appointment', r.status_code == 200 and r.json().get('status') == 'confirmed', f'status={r.json().get("status","")}', r)

        day_after = (date.today() + timedelta(days=2)).isoformat()
        r = requests.put(f'{BASE}/appointments/{booked_appt_id}/reschedule', headers=jennie_h, json={
            'new_date': day_after,
            'new_time': '14:00',
        })
        test('Reschedule appointment', r.status_code == 200, f'status={r.status_code}', r)
        rescheduled_id = r.json().get('id', '') if r.status_code == 200 else booked_appt_id

        cancel_target = rescheduled_id or booked_appt_id
        r = requests.put(f'{BASE}/appointments/{cancel_target}/cancel', headers=jennie_h, json={'reason': 'E2E test cleanup'})
        test('Cancel appointment', r.status_code == 200 and r.json().get('status') == 'cancelled', f'status={r.json().get("status","")}', r)
else:
    print('[SKIP] Appointment booking tests (no patient or appt type)')

r = requests.get(f'{BASE}/appointments/', headers=jennie_h, params={'from_date': tomorrow, 'to_date': tomorrow})
test('Filter appointments by date', r.status_code == 200, f'{r.json().get("total",0)} for {tomorrow}', r)

r = requests.get(f'{BASE}/appointments/', headers=jennie_h, params={'status': 'booked'})
test('Filter appointments by status', r.status_code == 200, f'{r.json().get("total",0)} booked', r)

r = requests.get(f'{BASE}/appointments/next-available', headers=jennie_h)
test('Next available slot', r.status_code in [200, 404], f'status={r.status_code}', r)

print()
print('--- 6. WEBHOOK / CALLS ---')

r = requests.get(f'{BASE}/webhooks/vapi/health')
test('Vapi webhook health', r.status_code == 200, r)

r = requests.get(f'{BASE}/webhooks/calls', headers=jennie_h)
test('List calls', r.status_code == 200, f'{r.json().get("total",0)} calls', r)

r = requests.get(f'{BASE}/webhooks/calls', headers=jennie_h, params={'direction': 'inbound'})
test('Filter calls by direction', r.status_code == 200, f'{r.json().get("total",0)} inbound', r)

vapi_event = {
    'message': {
        'type': 'status-update',
        'status': 'in-progress',
        'call': {
            'id': 'e2e-test-call-001',
            'type': 'inboundPhoneCall',
            'customer': {'number': '+15551234567'},
        }
    }
}
r = requests.post(f'{BASE}/webhooks/vapi', json=vapi_event)
test('Webhook accepts Vapi event', r.status_code == 200, r)

eocr_event = {
    'message': {
        'type': 'end-of-call-report',
        'call': {
            'id': 'e2e-test-call-001',
            'type': 'inboundPhoneCall',
            'cost': 0.05,
            'duration': 120,
        },
        'artifact': {
            'transcript': 'Patient: I need to book an appointment' + chr(10) + 'Assistant: Sure, let me help you with that.',
            'recordingUrl': 'https://example.com/recording.mp3',
        },
        'analysis': {
            'summary': 'Patient called to book appointment. Appointment scheduled for tomorrow at 10am.',
        },
        'endedReason': 'customer-ended-call',
    }
}
r = requests.post(f'{BASE}/webhooks/vapi', json=eocr_event)
test('Webhook handles end-of-call-report', r.status_code == 200, r)

tool_event = {
    'message': {
        'type': 'tool-calls',
        'call': {
            'id': 'e2e-test-call-002',
            'type': 'inboundPhoneCall',
        },
        'toolCallList': [
            {
                'id': 'tc-001',
                'name': 'check_patient_exists',
                'function': {
                    'name': 'check_patient_exists',
                    'arguments': json.dumps({'first_name': 'E2E_Test', 'last_name': 'Patient', 'dob': '1990-05-15'}),
                },
            }
        ],
    }
}
r = requests.post(f'{BASE}/webhooks/vapi', json=tool_event)
test('Webhook handles tool-calls', r.status_code == 200, r)
if r.status_code == 200:
    resp_data = r.json()
    test('Tool call returns results', 'results' in resp_data and len(resp_data.get('results', [])) > 0, f'results={resp_data}', r)

print()
print('--- 7. SMS ENDPOINTS ---')

r = requests.post(f'{BASE}/sms/send-confirmation/00000000-0000-0000-0000-000000000000', headers=jennie_h)
test('SMS send-confirmation with bad ID', r.status_code == 404, f'status={r.status_code}', r)

r = requests.post(f'{BASE}/sms/send-confirmation', headers=jennie_h, json={'appointment_id': '00000000-0000-0000-0000-000000000000'})
test('SMS send-confirmation (body format) with bad ID', r.status_code == 404, f'status={r.status_code}', r)

print()
print('--- 8. INSURANCE VERIFICATION ---')

r = requests.post(f'{BASE}/insurance/verify', headers=jennie_h, json={
    'patient_id': test_patient_id if test_patient_id else '00000000-0000-0000-0000-000000000000',
    'carrier_name': 'Aetna',
    'member_id': 'TEST123456',
})
test('Insurance verify endpoint exists', r.status_code in [200, 400, 422, 500, 502], f'status={r.status_code}', r)

print()
print('--- 9. EDGE CASES ---')

r = requests.get(f'{BASE}/patients/not-a-uuid', headers=jennie_h)
test('Invalid UUID returns 422', r.status_code == 422, f'status={r.status_code}', r)

r = requests.get(f'{BASE}/patients/00000000-0000-0000-0000-000000000000', headers=jennie_h)
test('Non-existent patient returns 404', r.status_code == 404, f'status={r.status_code}', r)

r = requests.get(f'{BASE}/appointments/00000000-0000-0000-0000-000000000000', headers=jennie_h)
test('Non-existent appointment returns 404', r.status_code == 404, f'status={r.status_code}', r)

r = requests.post(f'{BASE}/appointments/book', headers=jennie_h, json={
    'patient_id': test_patient_id or '00000000-0000-0000-0000-000000000000',
    'appointment_type_id': str(appt_type_id) if appt_type_id else '00000000-0000-0000-0000-000000000000',
    'date': 'not-a-date',
    'time': '10:00',
})
test('Invalid date format returns 422', r.status_code == 422, f'status={r.status_code}', r)

yesterday = (date.today() - timedelta(days=1)).isoformat()
r = requests.post(f'{BASE}/appointments/book', headers=jennie_h, json={
    'patient_id': test_patient_id or '00000000-0000-0000-0000-000000000000',
    'appointment_type_id': str(appt_type_id) if appt_type_id else '00000000-0000-0000-0000-000000000000',
    'date': yesterday,
    'time': '10:00',
})
test('Book in the past rejected', r.status_code in [400, 409, 422], f'status={r.status_code}', r)

if test_patient_id and appt_type_id:
    far_date = (date.today() + timedelta(days=10)).isoformat()
    r1 = requests.post(f'{BASE}/appointments/book', headers=jennie_h, json={
        'patient_id': test_patient_id,
        'appointment_type_id': str(appt_type_id),
        'date': far_date,
        'time': '09:00',
    })
    if r1.status_code == 201:
        r2 = requests.post(f'{BASE}/appointments/book', headers=jennie_h, json={
            'patient_id': test_patient_id,
            'appointment_type_id': str(appt_type_id),
            'date': far_date,
            'time': '09:00',
        })
        test('Double-book handled gracefully', r2.status_code in [201, 400, 409], f'status={r2.status_code}', r2)

r = requests.get(f'{BASE}/admin/practices', headers=doc_h)
test('Practice admin blocked from super admin', r.status_code == 403, f'status={r.status_code}', r)

r = requests.get(f'{BASE}/auth/me', headers={'Authorization': 'Bearer invalid.token.here'})
test('Invalid token returns 401', r.status_code == 401, f'status={r.status_code}', r)

r = requests.get(f'{BASE}/practice/schedule/overrides', headers=doc_h)
test('GET schedule overrides', r.status_code in [200, 404], f'status={r.status_code}', r)

print()
print('='*70)
print('  END-TO-END TEST RESULTS')
print('='*70)
print(f'  PASSED: {passed}')
print(f'  FAILED: {failed}')
print(f'  TOTAL:  {passed + failed}')
print()
if bugs:
    print('  BUGS FOUND:')
    for i, bug in enumerate(bugs, 1):
        print(f'    {i}. {bug}')
else:
    print('  No bugs found!')
print('='*70)
