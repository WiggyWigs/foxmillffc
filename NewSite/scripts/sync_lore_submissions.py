#!/usr/bin/env python3
"""
Syncs new responses from the "Manager Lore Submission" Google Form
into manager_lore.json. Run on a schedule via GitHub Actions.

Expects the linked Google Sheet's columns in the order Google Forms
writes them: Timestamp | Manager | Lore text (i.e. the form's two
questions, manager dropdown first, lore text second — if you reorder
the form's questions, update COL_MANAGER / COL_LORE_TEXT below to
match).

Tracks progress via lore_sync_state.json (just a row count) so each
run only processes rows it hasn't seen before — safe to run as often
as you like.

Credentials: expects the full service-account JSON key in the
GOOGLE_SHEETS_CREDENTIALS environment variable (set from a GitHub
Secret — see setup steps). The service account only needs Viewer
access to the Sheet; this script never writes to the Sheet, only
reads it.
"""

import json
import os
import sys
from pathlib import Path

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    sys.exit("ERROR: run 'pip install gspread google-auth' first.")

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
ROSTER_PATH = DATA_DIR / "manager_roster.json"
LORE_PATH = SCRIPT_DIR / "manager_lore.json"
SYNC_STATE_PATH = SCRIPT_DIR / "lore_sync_state.json"

# TODO: fill in your Google Sheet's ID (from its URL:
# https://docs.google.com/spreadsheets/d/SHEET_ID_IS_HERE/edit)
SHEET_ID = "1QrvXrUCEKDZPpN37tKXpYIpZI6vlv7fJZJrBb0CzGM8"

# Column layout in the response sheet (1-indexed, matching Google
# Forms' own column order: Timestamp is always column 1).
COL_MANAGER = 2
COL_LORE_TEXT = 3

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def load_roster():
    if not ROSTER_PATH.exists():
        sys.exit(f"ERROR: {ROSTER_PATH} not found.")
    with open(ROSTER_PATH) as f:
        return set(json.load(f)["managers"])


def load_lore():
    if not LORE_PATH.exists():
        return {}
    with open(LORE_PATH) as f:
        return json.load(f)


def load_sync_state():
    if not SYNC_STATE_PATH.exists():
        return {"last_row_processed": 1}  # row 1 is the header row
    with open(SYNC_STATE_PATH) as f:
        return json.load(f)


def main():
    if SHEET_ID.startswith("REPLACE_ME"):
        sys.exit("ERROR: SHEET_ID is still a placeholder — edit this script with your real Sheet ID.")

    creds_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    if not creds_json:
        sys.exit("ERROR: GOOGLE_SHEETS_CREDENTIALS environment variable not set.")

    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)

    try:
        sheet = client.open_by_key(SHEET_ID).sheet1
    except Exception as e:
        sys.exit(f"ERROR: couldn't open the sheet — check SHEET_ID and sharing permissions: {e}")

    all_rows = sheet.get_all_values()
    roster = load_roster()
    lore = load_lore()
    state = load_sync_state()
    last_processed = state["last_row_processed"]

    added_count = 0
    rejected = []

    # all_rows is 0-indexed in Python but 1-indexed as sheet rows;
    # row 1 is the header, so actual data starts at index 1 (row 2).
    for row_num in range(last_processed + 1, len(all_rows) + 1):
        row = all_rows[row_num - 1]
        manager = row[COL_MANAGER - 1].strip() if len(row) >= COL_MANAGER else ""
        lore_text = row[COL_LORE_TEXT - 1].strip() if len(row) >= COL_LORE_TEXT else ""

        if not manager or not lore_text:
            rejected.append(f"Row {row_num}: missing manager or lore text — skipped.")
            continue
        if manager not in roster:
            rejected.append(f"Row {row_num}: '{manager}' isn't a recognized manager — skipped.")
            continue

        existing = lore.get(manager, "").strip()
        lore[manager] = f"{existing} Also: {lore_text}" if existing else lore_text
        added_count += 1
        print(f"Row {row_num}: added lore for {manager}.")

    if added_count:
        with open(LORE_PATH, "w") as f:
            json.dump(lore, f, indent=2)

    with open(SYNC_STATE_PATH, "w") as f:
        json.dump({"last_row_processed": len(all_rows)}, f, indent=2)

    for msg in rejected:
        print(f"WARNING: {msg}")

    print(f"\nDone. {added_count} new lore entries added, "
          f"{len(rejected)} rows skipped, {len(all_rows) - last_processed} rows checked.")


if __name__ == "__main__":
    main()
