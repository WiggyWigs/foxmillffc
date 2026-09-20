#!/usr/bin/env python3
"""
Pulls the "Parlay" Google Sheet (published to the web as CSV) into
data/parlays.json, which the Parlay page (parlay.html / parlay.js)
fetches directly.

Unlike sync_lore_submissions.py (which only appends new rows and
tracks a last-row-processed cursor), this script rebuilds the ENTIRE
output fresh from the sheet on every run. Parlay Outcome values change
after the fact (e.g. "Pending" -> "Win"/"Loss" once a game is graded),
so an append-only sync would leave stale outcomes on the site. Same
philosophy as ingest_csv.py: nothing hand-edited or incrementally
patched — everything recomputed from the current source of truth
every run, so a corrected row on the sheet propagates automatically.

The sheet is published to the web (File > Share > Publish to web >
CSV) rather than shared with a service account, so — unlike
sync_lore_submissions.py — this needs NO credentials and no Google API
client library: it's a plain HTTP GET of the published CSV URL below
(urllib follows Google's redirect automatically), parsed with
Python's built-in csv module.

Expects the sheet's header row (in any column order, read by header
name, not position): Year, Week, Name, Bet, Odds, Outcome.

All "Name" values are validated against data/manager_roster.json, same
guardrail ingest_csv.py uses for manager names elsewhere — an
unrecognized name is rejected (row skipped, logged as a WARNING)
rather than silently creating a new, misspelled entry in the Parlay
Standings table.
"""

import csv
import io
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
ROSTER_PATH = DATA_DIR / "manager_roster.json"
PARLAYS_PATH = DATA_DIR / "parlays.json"

# Published-to-web CSV export of the Parlay sheet (File > Share >
# Publish to web, CSV format). If you ever republish or point this at
# a different sheet, update this URL to match the new one.
SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vT9gbWRe2LfduGjbKHt5cWdq8p2LT_vTXgDkCJetDh3v-5cDD2LA5NBI4Du-7n7VGnZolw-DbcsyeRG"
    "/pub?gid=0&single=true&output=csv"
)

REQUIRED_HEADERS = ["Year", "Week", "Name", "Bet", "Odds", "Outcome"]


def load_roster():
    if not ROSTER_PATH.exists():
        sys.exit(f"ERROR: {ROSTER_PATH} not found.")
    with open(ROSTER_PATH) as f:
        return set(json.load(f)["managers"])


def fetch_csv_rows():
    req = urllib.request.Request(SHEET_CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8-sig")
    except Exception as e:
        sys.exit(f"ERROR: couldn't fetch the published sheet CSV: {e}")
    return list(csv.DictReader(io.StringIO(raw)))


def main():
    records = fetch_csv_rows()

    if records:
        missing = [h for h in REQUIRED_HEADERS if h not in records[0]]
        if missing:
            sys.exit(f"ERROR: sheet is missing expected column(s): {', '.join(missing)}. "
                      f"Found: {', '.join(records[0].keys())}")

    roster = load_roster()

    picks = []
    rejected = []
    for i, row in enumerate(records, start=2):  # row 1 is the header row
        year_raw = (row.get("Year") or "").strip()
        week_raw = (row.get("Week") or "").strip()
        name = (row.get("Name") or "").strip()
        bet = (row.get("Bet") or "").strip()
        odds = (row.get("Odds") or "").strip()
        outcome = (row.get("Outcome") or "").strip()

        if not year_raw or not week_raw or not name or not bet:
            rejected.append(f"Row {i}: missing Year/Week/Name/Bet — skipped.")
            continue
        if name not in roster:
            rejected.append(f"Row {i}: '{name}' isn't a recognized manager — skipped.")
            continue
        try:
            year = int(year_raw)
        except ValueError:
            rejected.append(f"Row {i}: Year '{year_raw}' isn't a number — skipped.")
            continue

        picks.append({
            "year": year,
            "week": week_raw,
            "manager": name,
            "bet": bet,
            "odds": odds,
            "outcome": outcome,
        })

    for msg in rejected:
        print(f"WARNING: {msg}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(PARLAYS_PATH, "w") as f:
        json.dump({"last_updated": date.today().isoformat(), "picks": picks}, f, indent=2)

    print(f"\nDone. {len(picks)} picks written to {PARLAYS_PATH}, {len(rejected)} rows skipped.")


if __name__ == "__main__":
    main()
