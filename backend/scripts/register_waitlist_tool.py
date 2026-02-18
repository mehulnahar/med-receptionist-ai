"""Register add_to_waitlist tool on Vapi and link to Jenny assistant."""
import json
import urllib.request
import ssl

ASSISTANT_ID = "1bb4bc33-1605-44ee-87a3-259bee1a50e9"
VAPI_API_KEY = "c640cc8d-fd5c-4dd8-a29f-537d89beb9d8"
SERVER_URL = "https://backend-api-production-990c.up.railway.app/api/webhooks/vapi"
ctx = ssl.create_default_context()

def api_call(method, endpoint, data=None):
    url = f"https://api.vapi.ai{endpoint}"
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={
            "Authorization": f"Bearer {VAPI_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error = e.read().decode("utf-8")
        print(f"  ERROR {e.code}: {error[:500]}")
        return None

# Step 1: Create the add_to_waitlist tool
print("Creating add_to_waitlist tool...")
tool_def = {
    "type": "function",
    "function": {
        "name": "add_to_waitlist",
        "description": "Add a patient to the waitlist when no appointment slots are available. The patient will be notified by SMS when a slot opens up.",
        "parameters": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string", "description": "Full name of the patient"},
                "patient_phone": {"type": "string", "description": "Patient phone number for SMS notification"},
                "appointment_type": {"type": "string", "description": "Type of appointment needed"},
                "preferred_dates": {"type": "string", "description": "Preferred dates or date range"},
                "notes": {"type": "string", "description": "Additional notes"},
            },
            "required": ["patient_name", "patient_phone"],
        },
    },
    "server": {"url": SERVER_URL, "timeoutSeconds": 20},
}

result = api_call("POST", "/tool", tool_def)
if result and result.get("id"):
    new_tool_id = result["id"]
    print(f"  Created: {new_tool_id}")
else:
    print("  Failed to create tool!")
    exit(1)

# Step 2: Get current toolIds from assistant
print("\nFetching current assistant config...")
assistant = api_call("GET", f"/assistant/{ASSISTANT_ID}")
current_tool_ids = assistant.get("model", {}).get("toolIds", [])
print(f"  Current tools: {len(current_tool_ids)}")

# Step 3: Add new tool ID and update assistant
current_tool_ids.append(new_tool_id)
print(f"\nUpdating assistant with {len(current_tool_ids)} tools...")

# We need to preserve the existing model config
model = assistant.get("model", {})
model["toolIds"] = current_tool_ids

patch_data = {"model": model}
result = api_call("PATCH", f"/assistant/{ASSISTANT_ID}", patch_data)
if result:
    updated_ids = result.get("model", {}).get("toolIds", [])
    print(f"  Updated: {len(updated_ids)} tools")
    print(f"  Done!")
else:
    print("  Failed to update assistant!")
