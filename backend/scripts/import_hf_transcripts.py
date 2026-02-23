"""
Bulk-import HuggingFace healthcare call center transcripts into the Training pipeline
via the production Railway API.

This script:
1. Logs in to the production API as Jennie (practice_admin)
2. Creates a TrainingSession
3. Inserts each transcript as a pre-transcribed TrainingRecording via direct DB insert
   (uses a special /training/sessions/{id}/import-transcripts endpoint we add)
4. Triggers processing (GPT analysis) via the existing /process endpoint

Usage:
    python backend/scripts/import_hf_transcripts.py [--limit 50] [--categories Appointment Insurance]

Requirements:
    - Production Railway API must be running
    - requests library (pip install requests)
"""

import json
import sys
import time
import argparse
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library not installed. Run: pip install requests")
    sys.exit(1)

BASE_URL = "https://backend-api-production-990c.up.railway.app"
LOGIN_EMAIL = "jennie@stefanides.com"
LOGIN_PASSWORD = "secretary123"


def login() -> str:
    """Login and return access token."""
    print(f"Logging in as {LOGIN_EMAIL}...")
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": LOGIN_EMAIL,
        "password": LOGIN_PASSWORD,
    })
    if resp.status_code != 200:
        print(f"ERROR: Login failed ({resp.status_code}): {resp.text}")
        sys.exit(1)

    data = resp.json()
    token = data.get("access_token")
    if not token:
        print(f"ERROR: No access_token in response: {data}")
        sys.exit(1)

    print(f"  Logged in successfully!")
    return token


def create_session(token: str, name: str) -> str:
    """Create a training session and return its ID."""
    print(f"Creating training session: {name}")
    resp = requests.post(
        f"{BASE_URL}/api/training/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name},
    )
    if resp.status_code not in (200, 201):
        print(f"ERROR: Failed to create session ({resp.status_code}): {resp.text}")
        sys.exit(1)

    session_id = resp.json()["id"]
    print(f"  Session created: {session_id}")
    return session_id


def import_transcripts_via_api(token: str, session_id: str, transcripts: list) -> int:
    """Import transcripts via the bulk import endpoint."""
    print(f"Importing {len(transcripts)} transcripts...")

    resp = requests.post(
        f"{BASE_URL}/api/training/sessions/{session_id}/import-transcripts",
        headers={"Authorization": f"Bearer {token}"},
        json={"transcripts": transcripts},
    )
    if resp.status_code not in (200, 201):
        print(f"ERROR: Bulk import failed ({resp.status_code}): {resp.text}")
        return 0

    data = resp.json()
    count = data.get("imported", 0)
    print(f"  Imported {count} transcripts")
    return count


def start_processing(token: str, session_id: str):
    """Trigger GPT analysis on the session."""
    print(f"Starting GPT-4o-mini analysis...")
    resp = requests.post(
        f"{BASE_URL}/api/training/sessions/{session_id}/process",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code not in (200, 201):
        print(f"ERROR: Processing failed ({resp.status_code}): {resp.text}")
        return

    data = resp.json()
    print(f"  {data.get('message', 'Processing started')}")


def check_session_status(token: str, session_id: str) -> dict:
    """Check session status."""
    resp = requests.get(
        f"{BASE_URL}/api/training/sessions/{session_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code != 200:
        return {"status": "unknown"}
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description="Import HuggingFace healthcare transcripts into Training pipeline (via API)")
    parser.add_argument("--limit", type=int, default=50, help="Max transcripts to import (default: 50)")
    parser.add_argument("--categories", nargs="+", default=None, help="Filter categories (e.g. Appointment Insurance)")
    parser.add_argument("--skip-analysis", action="store_true", help="Skip GPT analysis (just import transcripts)")
    parser.add_argument("--poll", action="store_true", help="Poll for processing completion")
    args = parser.parse_args()

    # Load transcripts
    data_path = Path(__file__).resolve().parent.parent.parent / "data" / "training" / "healthcare_callcenter_receptionist.json"
    if not data_path.exists():
        data_path = Path(__file__).resolve().parent.parent.parent / "data" / "training" / "healthcare_callcenter_all.json"

    if not data_path.exists():
        print(f"ERROR: No transcript data found at {data_path}")
        print("Run the HuggingFace download script first.")
        sys.exit(1)

    with open(data_path, "r", encoding="utf-8") as f:
        all_transcripts = json.load(f)

    print(f"Loaded {len(all_transcripts)} transcripts from {data_path.name}")

    # Filter by categories
    if args.categories:
        all_transcripts = [
            t for t in all_transcripts
            if any(cat.lower() in t["category"].lower() for cat in args.categories)
        ]
        print(f"Filtered to {len(all_transcripts)} matching categories: {args.categories}")

    # Apply limit
    transcripts = all_transcripts[:args.limit]
    print(f"Will import {len(transcripts)} transcripts")

    # Login
    token = login()

    # Create session
    cat_label = " + ".join(args.categories) if args.categories else "All"
    session_name = f"HuggingFace Healthcare ({cat_label}) — {len(transcripts)} transcripts"
    session_id = create_session(token, session_name)

    # Prepare transcript payloads
    payload_transcripts = []
    for t in transcripts:
        text = t.get("transcript", "")
        if not text or len(text) < 50:
            continue
        payload_transcripts.append({
            "filename": f"hf_call_{t['id']:04d}_{t['category'].replace(' ', '_')[:30]}.txt",
            "transcript": text,
            "language": "en",
            "category": t.get("category", "Unknown"),
        })

    # Import in batches of 20 (API might have limits)
    total_imported = 0
    batch_size = 20
    for i in range(0, len(payload_transcripts), batch_size):
        batch = payload_transcripts[i:i + batch_size]
        count = import_transcripts_via_api(token, session_id, batch)
        total_imported += count
        if i + batch_size < len(payload_transcripts):
            print(f"  Progress: {total_imported}/{len(payload_transcripts)}")
            time.sleep(0.5)

    print(f"\nTotal imported: {total_imported}")

    # Start analysis
    if not args.skip_analysis and total_imported > 0:
        start_processing(token, session_id)

        if args.poll:
            print("\nPolling for completion (Ctrl+C to stop)...")
            while True:
                time.sleep(15)
                status_data = check_session_status(token, session_id)
                st = status_data.get("status", "unknown")
                processed = status_data.get("processed_count", 0)
                total = status_data.get("total_recordings", 0)
                print(f"  Status: {st} ({processed}/{total} processed)")
                if st in ("completed", "failed"):
                    break
            print(f"\nFinal status: {st}")
    else:
        print("\nTranscripts imported. To run analysis:")
        print(f"  1. Go to Training page in the dashboard")
        print(f"  2. Open session: {session_name}")
        print(f"  3. Click 'Process Recordings'")

    print(f"\n=== DONE ===")
    print(f"Session ID: {session_id}")
    print(f"Dashboard: https://frontend-production-4a41.up.railway.app/training")


if __name__ == "__main__":
    main()
