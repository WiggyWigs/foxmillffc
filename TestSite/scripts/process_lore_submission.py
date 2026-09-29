#!/usr/bin/env python3
"""
Parses a "lore-submission" labeled GitHub issue (created via input.html)
and appends its text to the named manager's entry in manager_lore.json.

Expects the issue body in the format written by input.js:
    Manager: <exact manager name>

    <lore text>

The manager name is validated against manager_roster.json — an
unrecognized name is rejected rather than silently creating a new,
possibly-misspelled entry (same guardrail philosophy as the CSV
ingestion's roster check).

Reads the issue body from the ISSUE_BODY environment variable (set by
the calling workflow from github.event.issue.body) and the issue
number from ISSUE_NUMBER, and writes a short result to
GITHUB_OUTPUT so the workflow can comment on/close the issue
appropriately.
"""

import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
ROSTER_PATH = DATA_DIR / "manager_roster.json"
LORE_PATH = SCRIPT_DIR / "manager_lore.json"


def set_output(name, value):
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        # Multiline-safe output, since lore text or error messages may
        # contain newlines.
        delimiter = "EOF_MARKER"
        with open(gh_output, "a") as f:
            f.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def main():
    body = os.environ.get("ISSUE_BODY", "")
    match = re.match(r"Manager:\s*(.+?)\n+(.+)", body, re.DOTALL)
    if not match:
        set_output("result", "rejected")
        set_output("message", "Couldn't parse the submission format — no changes made.")
        return

    manager = match.group(1).strip()
    lore_text = match.group(2).strip()

    if not ROSTER_PATH.exists():
        set_output("result", "rejected")
        set_output("message", f"{ROSTER_PATH} not found — no changes made.")
        return
    with open(ROSTER_PATH) as f:
        roster = set(json.load(f)["managers"])

    if manager not in roster:
        set_output("result", "rejected")
        set_output("message", f"'{manager}' isn't a recognized manager name — no changes made. "
                               f"Check for typos and resubmit.")
        return

    if not lore_text:
        set_output("result", "rejected")
        set_output("message", "No lore text found in the submission — no changes made.")
        return

    lore = {}
    if LORE_PATH.exists():
        with open(LORE_PATH) as f:
            lore = json.load(f)

    existing = lore.get(manager, "").strip()
    lore[manager] = f"{existing} Also: {lore_text}" if existing else lore_text

    with open(LORE_PATH, "w") as f:
        json.dump(lore, f, indent=2)

    set_output("result", "added")
    set_output("message", f"Added to {manager}'s lore:\n\n> {lore_text}")


if __name__ == "__main__":
    main()
