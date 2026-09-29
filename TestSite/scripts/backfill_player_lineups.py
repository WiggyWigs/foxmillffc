#!/usr/bin/env python3
"""
One-time backfill: captures individual player lineup data (starters +
bench, each player's points and real NFL game date) for every REGULAR
SEASON week of every historical year — not just the going-forward
capture that capture_latest_lineups() in espn_pull.py already does.

WHY THIS EXISTS
---------------
The normal weekly automation only ever captures the current week's
lineups going forward from whenever it was first run. Nothing before
that point was ever saved, even though ESPN's API can still serve
historical box scores for past weeks within a season. This script
fills in that gap once, so features like top/bottom scorer, the
bench-swap analysis, and the Monday Night Football swing detection
can work on ANY historical week, not just recent ones.

SCOPE — REGULAR SEASON ONLY
----------------------------
This deliberately does NOT backfill playoff weeks (ESPN's raw
box_scores(week=X) numbering for playoffs doesn't match the P1/P2/P3
labels used elsewhere in this project, and getting that translation
wrong risks silently mislabeling data). All of the features that
currently use player_lineups.json only ever look at regular-season
games anyway, so this covers everything actually usable today.

USAGE
-----
    python backfill_player_lineups.py

Run it once, locally or via a manual GitHub Actions dispatch — this
is NOT meant to run as part of the regular weekly automation. It's
safe to run more than once: existing (year, week, manager) entries
are skipped, same de-duplication as the regular capture.

This will make a real number of API calls (roughly: number of
historical seasons x weeks per season), so expect it to take a
while and go easy on how often you re-run it.
"""

from espn_api.football import League
import json
import os
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
TEAM_MAPPING_PATH = SCRIPT_DIR / "team_mapping.json"
PLAYER_LINEUPS_PATH = DATA_DIR / os.environ.get("PLAYER_LINEUPS_FILENAME", "player_lineups.json")

# Only backfill seasons that have already finished — the current
# in-progress season is already covered by the normal going-forward
# capture, so re-doing it here would just waste API calls.
HISTORICAL_YEARS = [2023, 2024, 2025]

LEAGUE_ID = os.environ.get("ESPN_LEAGUE_ID")
SWID = os.environ.get("ESPN_SWID")
ESPN_S2 = os.environ.get("ESPN_S2")
if not (LEAGUE_ID and SWID and ESPN_S2):
    try:
        from espn_config import LEAGUE_ID, SWID, ESPN_S2  # local-only, never committed
    except ImportError:
        sys.exit(
            "ERROR: ESPN credentials not found. Set ESPN_LEAGUE_ID / ESPN_SWID / "
            "ESPN_S2 as environment variables, or create espn_config.py locally."
        )


def load_team_mapping():
    if not TEAM_MAPPING_PATH.exists():
        return {}
    with open(TEAM_MAPPING_PATH) as f:
        entries = json.load(f)
    return {(e["year"], e["team_name"]): e["manager"] for e in entries}


def load_existing_lineups():
    if not PLAYER_LINEUPS_PATH.exists():
        return []
    with open(PLAYER_LINEUPS_PATH) as f:
        return json.load(f)


def backfill_year(year, resolved_mapping, existing_keys):
    year_str = str(year)
    print(f"\n--- {year} ---")
    try:
        league = League(league_id=LEAGUE_ID, year=year, espn_s2=ESPN_S2, swid=SWID)
    except Exception as e:
        print(f"WARNING: couldn't load league for {year}: {e}")
        return []

    regular_season_weeks = league.settings.reg_season_count
    new_entries = []

    for week in range(1, regular_season_weeks + 1):
        try:
            box_scores = league.box_scores(week=week)
        except Exception as e:
            print(f"  Week {week}: WARNING — couldn't fetch box scores: {e}")
            continue

        week_new = 0
        for bs in box_scores:
            for team, lineup in ((bs.away_team, bs.away_lineup), (bs.home_team, bs.home_lineup)):
                if team is None:
                    continue
                manager = resolved_mapping.get((year_str, team.team_name))
                if manager is None:
                    print(f"  Week {week}: WARNING — unmapped team {team.team_name!r}, skipping")
                    continue
                key = (year_str, str(week), manager)
                if key in existing_keys:
                    continue

                players = [
                    {
                        "name": p.name,
                        "position": p.position,
                        "slot": p.slot_position,
                        "points": p.points,
                        "started": p.slot_position not in ("BE", "IR"),
                        "eligible_slots": getattr(p, "eligibleSlots", []),
                        "game_date": getattr(p, "game_date", None).isoformat()
                        if getattr(p, "game_date", None) else None,
                    }
                    for p in lineup
                ]
                new_entries.append({
                    "year": year_str, "week": str(week),
                    "manager": manager, "players": players,
                })
                existing_keys.add(key)
                week_new += 1

        print(f"  Week {week}: {week_new} new manager-lineups captured")
        time.sleep(0.5)  # be a reasonable citizen about API load

    return new_entries


def main():
    resolved_mapping = load_team_mapping()
    if not resolved_mapping:
        sys.exit(f"ERROR: {TEAM_MAPPING_PATH} not found or empty — can't resolve team names to managers.")

    existing = load_existing_lineups()
    existing_keys = {(e["year"], e["week"], e["manager"]) for e in existing}
    print(f"Starting with {len(existing)} existing lineup entries.")

    all_new = []
    for year in HISTORICAL_YEARS:
        all_new.extend(backfill_year(year, resolved_mapping, existing_keys))

    if not all_new:
        print("\nNothing new to add — historical data may already be fully captured.")
        return

    existing.extend(all_new)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(PLAYER_LINEUPS_PATH, "w") as f:
        json.dump(existing, f, indent=2)

    print(f"\nDone. Added {len(all_new)} new manager-lineup entries. "
          f"{len(existing)} total now in {PLAYER_LINEUPS_PATH}.")


if __name__ == "__main__":
    main()
