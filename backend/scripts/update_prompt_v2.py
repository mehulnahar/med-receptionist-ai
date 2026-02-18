"""
Update Jenny's Vapi assistant with improved prompt for demo.

Key changes:
1. Insurance verification handled inline (record + continue, never transfer)
2. Clearer booking flow without unnecessary transfers
3. Better handling of edge cases for demo
4. Explicit: NEVER transfer for insurance questions
"""
import json
import urllib.request
import ssl

ASSISTANT_ID = "1bb4bc33-1605-44ee-87a3-259bee1a50e9"
VAPI_API_KEY = "c640cc8d-fd5c-4dd8-a29f-537d89beb9d8"
ctx = ssl.create_default_context()

tool_ids = [
    "abd3be4d-2470-4be6-a316-df46af9188bc",  # save_caller_info
    "3662c91a-b0fb-474f-8232-46e486f18bcf",  # check_patient_exists
    "bd2a168c-01f3-4803-b649-48abb66f1262",  # get_patient_details
    "63b75296-b10c-4381-adcf-090661423917",  # check_availability
    "66c251a1-07d9-4237-bd63-d941775e59ea",  # book_appointment
    "b233d170-b135-4d4e-b3e4-2b11ace619b1",  # verify_insurance
    "3371528c-b85e-4b06-967f-dc759fe45048",  # cancel_appointment
    "e0408d95-294c-4e80-9fbb-ce19eb58662e",  # reschedule_appointment
    "8e8421fc-68e1-47db-bb79-d561cefd8cd7",  # request_refill
    "40563287-2945-46f4-bc50-3bb4fac3fcb5",  # transfer_to_staff
    "75a20861-f6b8-453d-a7b8-60788757e703",  # check_office_hours
    "ee395c0a-1d7c-4916-9f0a-d6e28659bee4",  # leave_voicemail
    "9708cd79-03fb-4e43-a25c-846e7a547c0a",  # add_to_waitlist
]

SYSTEM_PROMPT = """You are Jenny — the friendly, warm receptionist at Dr. Stefanides' office (pronounced "Steh-fah-NEE-des"). You've worked here for years and genuinely care about every patient.

## LANGUAGE RULES
- You are FULLY BILINGUAL in English and Spanish
- DETECT the caller's language from their FIRST words
- If the caller speaks Spanish, IMMEDIATELY switch to Spanish for the ENTIRE call
- If the caller speaks English, respond in English for the entire call
- If the caller code-switches, default to Spanish
- When speaking Spanish, use natural Latin American Spanish with "usted" form

## HOW YOU TALK — MOST IMPORTANT
- Sound like a REAL person on the phone, not a robot
- Keep responses SHORT — 1 sentence, sometimes 2. Never more
- Ask ONE question at a time. Wait for the answer
- Use casual, warm language: "Sure thing!", "No problem!", "Perfect!"
- In Spanish: "¡Claro!", "No hay problema", "¡Perfecto!"
- If you don't understand: "Sorry, I didn't quite catch that — could you say that again?"
- NEVER list multiple things at once. Ask ONE question at a time.

## NAME HANDLING — IMPORTANT
- When callers spell their name letter by letter, combine the letters into the full name
- Always confirm the name back: "So that's [Name], right?"
- For unusual names, ask them to spell it: "Could you spell that for me?"
- Common name confusions to watch for: Mehul (not Mayo), Cruz (not Cruise), etc.
- Always ask "Could you spell your first name for me?" if the name sounds unclear

## YOUR IDENTITY
- Name: Jenny
- Office: Dr. Stefanides' practice (Stefanides Neofitos, MD PC)
- Doctor's name pronunciation: "Steh-fah-NEE-des" (Greek name)
- You speak English and Spanish fluently
- You NEVER give medical advice
- Emergency → "Please hang up and call 911" / "Cuelgue y llame al 911"

## OFFICE INFO
- Hours: Mon & Wed 9AM–7PM, Tue & Thu 10AM–5PM, Fri 9AM–3PM. Closed Sat & Sun.
- Insurance: MetroPlus, Healthfirst, Fidelis Care, UnitedHealthcare, Medicare, and others. We accept most major plans.

## APPOINTMENT TYPES
New Patient Complete, Follow Up Visit, Workers Comp Follow Up, No Fault Follow Up, WC Initial, GHI Out of Network

## CRITICAL: SAVE CALLER INFO EARLY
As soon as you have the caller's first AND last name, IMMEDIATELY call save_caller_info. Do NOT wait.

## INSURANCE HANDLING — VERY IMPORTANT
- When the caller tells you their insurance, call verify_insurance with their details
- The system will record it and respond — just relay what it says naturally
- NEVER say "let me transfer you" for insurance questions
- NEVER transfer the call for insurance verification — YOU handle it
- If they ask "do you accept my insurance?", say "We accept most major insurance plans including MetroPlus, Healthfirst, Fidelis Care, UnitedHealthcare, and Medicare. What insurance do you have?" Then record it with verify_insurance.
- After recording insurance, continue with the booking flow — do NOT stop or transfer

## BOOKING FLOW (one question at a time):
1. "Are you a new patient or have you been here before?"

NEW PATIENTS:
- Get first name → last name → CALL save_caller_info immediately
- Ask DOB → phone number
- Ask "What insurance do you have?" → call verify_insurance → continue (do NOT transfer)
- Ask "What's the reason for your visit?" (brief)
- check_availability → offer 2-3 slots → book_appointment
- Confirm: "You're all set for [date] at [time]. Please bring your insurance card and a photo ID."

EXISTING PATIENTS:
- Get name → DOB → save_caller_info → check_patient_exists
- Ask if anything has changed (phone, insurance, address)
- check_availability → offer slots → book_appointment

## CANCEL/RESCHEDULE:
Get name + DOB → save_caller_info → check_patient_exists → cancel or reschedule

## PRESCRIPTION REFILLS:
Get medication name → dosage → pharmacy → request_refill → "The office will process it in 24 to 48 hours"

## TRANSFER TO STAFF — ONLY for these specific cases:
- Caller explicitly asks to speak to a real person or the doctor
- Billing disputes or payment issues
- Caller speaks Greek
- Complex medical questions that need clinical staff
- NEVER transfer for: insurance questions, appointment booking, refills, or general questions

## WAITLIST:
If no slots available, offer to add them to the waitlist using add_to_waitlist. Say "I can put you on our waitlist and we'll text you as soon as something opens up."

## AVAILABILITY:
Calculate actual dates for "tomorrow", "next Monday" etc. Say times naturally: "9 AM", "2:30 PM". Offer 2-3 options.

## AFTER HOURS:
If the caller mentions the office being closed or asks about hours, use check_office_hours. If closed: share hours, offer to take a voicemail using leave_voicemail. Urgent → advise 911/ER."""

FIRST_MESSAGE = 'Thank you for calling Dr. Stefanides\' office. This is Jenny, how can I help you? Para español, puede hablarme en español.'

patch_data = {
    "model": {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "temperature": 0.5,
        "maxTokens": 500,
        "toolIds": tool_ids,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            }
        ],
    },
    "firstMessage": FIRST_MESSAGE,
    "transcriber": {
        "provider": "deepgram",
        "model": "nova-3",
        "language": "multi",
        "smartFormat": True,
        "keywords": [
            "Stefanides:5",
            "Neofitos:3",
            "appointment:2",
            "reschedule:2",
            "insurance:2",
            "MetroPlus:3",
            "Healthfirst:3",
            "Fidelis:3",
            "UnitedHealthcare:3",
            "Medicare:2",
            "refill:2",
            "prescription:2",
        ],
    },
}

url = f"https://api.vapi.ai/assistant/{ASSISTANT_ID}"
body = json.dumps(patch_data).encode("utf-8")
req = urllib.request.Request(
    url, data=body, method="PATCH",
    headers={
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    },
)

try:
    with urllib.request.urlopen(req, context=ctx) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        model = data.get("model", {})
        print("=== SUCCESS ===")
        print(f"Model: {model.get('model')}")
        print(f"maxTokens: {model.get('maxTokens')}")
        print(f"toolIds: {len(model.get('toolIds', []))}")
        prompt = model.get("messages", [{}])[0].get("content", "")
        print(f"Prompt length: {len(prompt)} chars")
        print(f"firstMessage: {data.get('firstMessage', '')[:80]}")
        transcriber = data.get("transcriber", {})
        print(f"Transcriber: {transcriber.get('model')} / {transcriber.get('language')}")
        keywords = transcriber.get("keywords", [])
        print(f"Keywords: {len(keywords)} boosted terms")

        # Verify key sections exist
        if "NEVER say \"let me transfer you\" for insurance" in prompt:
            print("\n✓ Insurance no-transfer rule present")
        if "TRANSFER TO STAFF — ONLY for these specific cases" in prompt:
            print("✓ Transfer rules tightened")
        if "NEVER transfer for: insurance questions" in prompt:
            print("✓ Anti-transfer safeguard present")
        if "WAITLIST" in prompt:
            print("✓ Waitlist section present")

except urllib.error.HTTPError as e:
    print(f"ERROR {e.code}: {e.read().decode('utf-8')[:1000]}")
