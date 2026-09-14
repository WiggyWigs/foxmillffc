#!/usr/bin/env python3
"""
Full pipeline: pulls matchup scores from ESPN's (unofficial, undocumented)
fantasy football API, maps team names to managers, writes the CSV
ingest_csv.py expects, then runs ingest_csv.py against it — producing an
updated stats.json and banner in one shot.

Designed to run two ways:
  1. Locally, for testing — credentials come from espn_config.py
     (never committed to the repo).
  2. In GitHub Actions on a schedule — credentials come from environment
     variables (set from GitHub Secrets, never written to any file).

KNOWN LIMITATIONS (read before relying on this)
-------------------------------------------------
- Uses ESPN's PRIVATE, undocumented API — not officially supported,
  could change or break without notice, sits in a gray area of ESPN's
  terms of service. Low practical risk for a small private league,
  zero guarantee of continued access.
- The team-name mapping (team_mapping.json) only knows names we've
  already seen. A new season, or a mid-season rename, produces an
  unmapped name UNLESS exactly one team is unrecognized and exactly
  one manager is otherwise unaccounted for that week — in that case,
  process of elimination resolves it automatically and saves the
  result back to team_mapping.json for future runs. Two simultaneous
  unknowns in the same week can't be resolved this way and require a
  manual edit to team_mapping.json.
- Playoff filtering keeps only matchup_type == "WINNERS_BRACKET",
  confirmed correct against 2023-2025 real data (5 playoff games/year,
  matching this league's 6-team/2-bye bracket). Not guaranteed to hold
  if the league's bracket structure ever changes.
"""

from espn_api.football import League
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CSV_OUTPUT_PATH = SCRIPT_DIR / os.environ.get("CSV_OUTPUT_FILENAME", "espn_pull_latest.csv")
UPCOMING_MATCHUPS_PATH = SCRIPT_DIR.parent / "data" / os.environ.get("UPCOMING_MATCHUPS_FILENAME", "upcoming_matchups.json")

# Test-cutoff mode: when both are set, the pull pretends the season only
# progressed through this year/week — everything after is excluded, and
# the "upcoming matchups" file is built from the real schedule for the
# week right after the cutoff (using ESPN's own real historical data,
# just ignoring its scores). This is what lets a full pipeline test run
# safely in GitHub Actions against real past data without ever touching
# live current-season files, by pointing every *_FILENAME env var above
# at test-only names.
TEST_CUTOFF_YEAR = os.environ.get("TEST_CUTOFF_YEAR")
TEST_CUTOFF_WEEK = os.environ.get("TEST_CUTOFF_WEEK")
if TEST_CUTOFF_YEAR:
    TEST_CUTOFF_YEAR = int(TEST_CUTOFF_YEAR)
if TEST_CUTOFF_WEEK:
    TEST_CUTOFF_WEEK = int(TEST_CUTOFF_WEEK)
INGEST_SCRIPT_PATH = SCRIPT_DIR / "ingest_csv.py"

LEAGUE_ID = 1222412013
YEARS = [2023, 2024, 2025, 2026]

# Games with a 0-0 score are ESPN placeholders for not-yet-played weeks —
# never real results, always excluded regardless of year.
EXCLUDE_ZERO_ZERO = True

REAL_PLAYOFF_TYPE = "WINNERS_BRACKET"

TEAM_MAPPING_PATH = SCRIPT_DIR / "team_mapping.json"


def load_team_mapping():
    """(Year, Team_Name) -> Manager, loaded from team_mapping.json.
    This file is the single source of truth — edit it directly for
    manual corrections, or let auto-resolution (see below) append to
    it automatically."""
    if not TEAM_MAPPING_PATH.exists():
        return {}
    with open(TEAM_MAPPING_PATH) as f:
        entries = json.load(f)
    return {(e["year"], e["team_name"]): e["manager"] for e in entries}


def save_team_mapping(mapping):
    """Writes the full mapping back out, sorted for a clean diff each
    time — so `git diff` on this file only ever shows genuinely new
    entries, not reordering noise."""
    entries = [
        {"year": year, "team_name": name, "manager": manager}
        for (year, name), manager in mapping.items()
    ]
    entries.sort(key=lambda e: (e["year"], e["team_name"]))
    with open(TEAM_MAPPING_PATH, "w") as f:
        json.dump(entries, f, indent=2)


def load_credentials():
    """Environment variables first (GitHub Actions / CI), local config
    file second (your own machine). Never both required at once."""
    env_league = os.environ.get("ESPN_LEAGUE_ID")
    env_swid = os.environ.get("ESPN_SWID")
    env_s2 = os.environ.get("ESPN_S2")
    if env_swid and env_s2:
        return int(env_league or LEAGUE_ID), env_swid, env_s2

    try:
        from espn_config import LEAGUE_ID as cfg_league, SWID as cfg_swid, ESPN_S2 as cfg_s2
        return cfg_league, cfg_swid, cfg_s2
    except ImportError:
        sys.exit(
            "No credentials found. Either set ESPN_SWID / ESPN_S2 environment "
            "variables, or save espn_config_template.py as espn_config.py "
            "with your values filled in."
        )


def playoff_week_label(matchup, week, regular_season_weeks):
    if not matchup.is_playoff:
        return str(week)
    playoff_week_index = week - regular_season_weeks
    return f"P{playoff_week_index}"


def pull_all_scores(league_id, swid, espn_s2):
    rows = []
    unmapped = set()

    # Working copy that grows during the run: when exactly one name is
    # unrecognized in a week AND exactly one manager (from that year's
    # known roster) isn't otherwise accounted for that same week, we
    # infer the rename and remember it for all subsequent weeks too.
    # Two simultaneous unknowns in the same week can't be resolved this
    # way — those fall through to the hard failure below, same as any
    # other unmapped name.
    resolved = load_team_mapping()
    any_new_resolutions = False

    for year in YEARS:
        if TEST_CUTOFF_YEAR and year > TEST_CUTOFF_YEAR:
            continue  # test-cutoff mode: pretend later years haven't happened

        year_str = str(year)
        league = League(league_id=league_id, year=year, espn_s2=espn_s2, swid=swid)
        regular_season_weeks = league.settings.reg_season_count
        total_weeks = regular_season_weeks + 4

        # Full expected roster for this year, from whatever's mapped
        # so far (grows if auto-resolution adds a new name this year).
        year_roster = {mgr for (y, _), mgr in resolved.items() if y == year_str}

        for week in range(1, total_weeks + 1):
            if TEST_CUTOFF_YEAR and year == TEST_CUTOFF_YEAR and TEST_CUTOFF_WEEK and week > TEST_CUTOFF_WEEK:
                break  # test-cutoff mode: pretend later weeks haven't happened

            try:
                matchups = league.scoreboard(week=week)
            except Exception:
                break
            if not matchups:
                break

            # Filter down to real, playable, non-placeholder matchups
            # once, up front — everything below works off this list.
            week_matchups = []
            for m in matchups:
                away = getattr(m, "away_team", None)
                home = getattr(m, "home_team", None)
                if away is None or home is None:
                    continue
                if m.is_playoff and m.matchup_type != REAL_PLAYOFF_TYPE:
                    continue
                if EXCLUDE_ZERO_ZERO and m.away_score == 0 and m.home_score == 0:
                    continue
                week_matchups.append((m, away, home))
            if not week_matchups:
                continue

            # Pass 1: who's resolved this week, who isn't.
            unresolved_names_this_week = set()
            matched_managers_this_week = set()
            for m, away, home in week_matchups:
                for side in (away, home):
                    mgr = resolved.get((year_str, side.team_name))
                    if mgr is None:
                        unresolved_names_this_week.add(side.team_name)
                    else:
                        matched_managers_this_week.add(mgr)

            # Process-of-elimination: exactly one gap on each side.
            missing_managers = year_roster - matched_managers_this_week
            if len(unresolved_names_this_week) == 1 and len(missing_managers) == 1:
                new_name = next(iter(unresolved_names_this_week))
                inferred_manager = next(iter(missing_managers))
                resolved[(year_str, new_name)] = inferred_manager
                year_roster.add(inferred_manager)
                any_new_resolutions = True
                print(f"AUTO-RESOLVED: {year_str} {new_name!r} -> {inferred_manager} "
                      f"(process of elimination, week {week})")
                unresolved_names_this_week = set()

            for name in unresolved_names_this_week:
                unmapped.add((year_str, name))

            # Pass 2: build the actual rows.
            for m, away, home in week_matchups:
                week_label = playoff_week_label(m, week, regular_season_weeks)
                away_mgr = resolved.get((year_str, away.team_name))
                home_mgr = resolved.get((year_str, home.team_name))
                rows.append({
                    "Year": year_str, "Week": week_label,
                    "Away Team": away.team_name, "Home Team": home.team_name,
                    "Away Score": m.away_score, "Home Score": m.home_score,
                    "Away Manager": away_mgr or "", "Home Manager": home_mgr or "",
                })

    if any_new_resolutions:
        save_team_mapping(resolved)
        print(f"Saved updated mapping to {TEAM_MAPPING_PATH}")

    return rows, unmapped


PLAYER_LINEUPS_PATH = SCRIPT_DIR.parent / "data" / os.environ.get("PLAYER_LINEUPS_FILENAME", "player_lineups.json")


def capture_latest_lineups(league_id, swid, espn_s2, resolved_mapping):
    """
    Pulls individual player lineup data (starters + bench, each player's
    points that week) for the current year's most recently completed
    week only — appended to player_lineups.json incrementally, same
    de-duplication approach as the score data itself. Historical
    seasons are NOT backfilled by this; it only ever adds the newest
    week going forward from whenever this is first run.

    In test-cutoff mode, "most recently completed" means TEST_CUTOFF_WEEK
    specifically, not whatever the real season's actual final week was.
    """
    year = TEST_CUTOFF_YEAR if TEST_CUTOFF_YEAR else max(YEARS)
    year_str = str(year)
    league = League(league_id=league_id, year=year, espn_s2=espn_s2, swid=swid)
    regular_season_weeks = league.settings.reg_season_count

    existing = []
    if PLAYER_LINEUPS_PATH.exists():
        with open(PLAYER_LINEUPS_PATH) as f:
            existing = json.load(f)
    existing_keys = {(e["year"], e["week"], e["manager"]) for e in existing}

    if TEST_CUTOFF_WEEK:
        latest_completed_week = TEST_CUTOFF_WEEK
    else:
        # Find the most recently completed week (last one with real scores).
        latest_completed_week = None
        for week in range(1, regular_season_weeks + 5):
            try:
                matchups = league.scoreboard(week=week)
            except Exception:
                break
            real = [m for m in matchups if getattr(m, "away_team", None) and getattr(m, "home_team", None)]
            if not real:
                break
            if any(m.away_score != 0 or m.home_score != 0 for m in real):
                latest_completed_week = week
            else:
                break  # first unplayed week — stop, we found the latest completed one already

    if latest_completed_week is None:
        print("No completed weeks found — skipping lineup capture.")
        return

    try:
        box_scores = league.box_scores(week=latest_completed_week)
    except Exception as e:
        print(f"WARNING: couldn't fetch box scores for week {latest_completed_week}: {e}")
        return

    new_entries = []
    for bs in box_scores:
        for team, lineup in ((bs.away_team, bs.away_lineup), (bs.home_team, bs.home_lineup)):
            if team is None:
                continue
            manager = resolved_mapping.get((year_str, team.team_name))
            if manager is None:
                continue  # unmapped team name — same safety net as the score pull
            key = (year_str, str(latest_completed_week), manager)
            if key in existing_keys:
                continue

            players = [
                {
                    "name": p.name,
                    "position": p.position,
                    "slot": p.slot_position,
                    "points": p.points,
                    "started": p.slot_position not in ("BE", "IR"),
                }
                for p in lineup
            ]
            new_entries.append({
                "year": year_str, "week": str(latest_completed_week),
                "manager": manager, "players": players,
            })

    if not new_entries:
        print(f"No new lineup entries for week {latest_completed_week} (already captured, or nothing mapped).")
        return

    existing.extend(new_entries)
    with open(PLAYER_LINEUPS_PATH, "w") as f:
        json.dump(existing, f, indent=2)
    print(f"Added {len(new_entries)} manager-lineups for week {latest_completed_week} to {PLAYER_LINEUPS_PATH}")


def capture_upcoming_matchups(league_id, swid, espn_s2, resolved_mapping):
    """
    Finds the current (max) year's next unplayed week and saves just the
    matchup pairings (manager names, no scores — they haven't happened
    yet) to upcoming_matchups.json. This is the schedule data that gets
    thrown away by the 0-0 filter in pull_all_scores, but the "Game of
    the Week" preview needs to know who's playing whom next week.

    In test-cutoff mode, "next week" means TEST_CUTOFF_WEEK + 1 —
    grabbing that week's real pairings from ESPN's history and
    deliberately ignoring that it already has a real score, since
    we're pretending the season only got as far as the cutoff.
    """
    year = TEST_CUTOFF_YEAR if TEST_CUTOFF_YEAR else max(YEARS)
    year_str = str(year)
    league = League(league_id=league_id, year=year, espn_s2=espn_s2, swid=swid)
    regular_season_weeks = league.settings.reg_season_count

    if TEST_CUTOFF_WEEK:
        target_weeks = [TEST_CUTOFF_WEEK + 1]
    else:
        target_weeks = range(1, regular_season_weeks + 5)

    for week in target_weeks:
        try:
            matchups = league.scoreboard(week=week)
        except Exception:
            break
        if not matchups:
            break

        real_matchups = [
            m for m in matchups
            if getattr(m, "away_team", None) and getattr(m, "home_team", None)
        ]
        if not real_matchups:
            continue

        # Outside test mode, an unplayed week is identified by every
        # game showing 0-0 — skip weeks that have already happened.
        if not TEST_CUTOFF_WEEK and any(m.away_score != 0 or m.home_score != 0 for m in real_matchups):
            continue

        pairings = []
        for m in real_matchups:
            away_mgr = resolved_mapping.get((year_str, m.away_team.team_name))
            home_mgr = resolved_mapping.get((year_str, m.home_team.team_name))
            if away_mgr and home_mgr:
                pairings.append({"away_manager": away_mgr, "home_manager": home_mgr})

        output = {"year": year, "week": week, "matchups": pairings}
        with open(UPCOMING_MATCHUPS_PATH, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Wrote {len(pairings)} upcoming matchups (Week {week}, {year}) to {UPCOMING_MATCHUPS_PATH}")
        return

    print("No upcoming unplayed week found — skipping upcoming_matchups.json.")


def main():
    league_id, swid, espn_s2 = load_credentials()

    rows, unmapped = pull_all_scores(league_id, swid, espn_s2)

    if unmapped:
        print("FAILED: unmapped team names found (more than one gap in the same "
              "week, so process-of-elimination couldn't resolve it) — refusing "
              "to produce output.")
        print(f"Add these to {TEAM_MAPPING_PATH.name}, then re-run:")
        for year, name in sorted(unmapped):
            print(f'  {{"year": "{year}", "team_name": "{name}", "manager": "???"}},')
        sys.exit(1)

    with open(CSV_OUTPUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "Year", "Week", "Away Team", "Home Team",
            "Away Score", "Home Score", "Away Manager", "Home Manager",
        ])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {CSV_OUTPUT_PATH}")

    # Snapshot the current stats.json BEFORE ingest_csv.py overwrites it —
    # this is what lets generate_recap.py detect "new record set this
    # week" by comparing before/after. Scratch file, not committed.
    stats_path = SCRIPT_DIR.parent / "data" / os.environ.get("STATS_FILENAME", "stats.json")
    stats_snapshot_path = SCRIPT_DIR.parent / "data" / os.environ.get("STATS_SNAPSHOT_FILENAME", "stats_previous_run.json")
    if stats_path.exists():
        import shutil
        shutil.copy(stats_path, stats_snapshot_path)

    # Chain straight into ingest_csv.py — one script run, one result.
    result = subprocess.run(
        [sys.executable, str(INGEST_SCRIPT_PATH), str(CSV_OUTPUT_PATH)],
        cwd=SCRIPT_DIR,
    )
    if result.returncode != 0:
        sys.exit("ingest_csv.py failed — see output above.")

    try:
        capture_upcoming_matchups(league_id, swid, espn_s2, load_team_mapping())
    except Exception as e:
        # Non-fatal — the recap step downstream just won't have a
        # "Game of the Week" preview this run if this fails.
        print(f"WARNING: couldn't capture upcoming matchups: {e}")

    try:
        capture_latest_lineups(league_id, swid, espn_s2, load_team_mapping())
    except Exception as e:
        # Non-fatal — the "highest scoring player" callout just won't
        # have data this run if this fails.
        print(f"WARNING: couldn't capture lineups: {e}")


if __name__ == "__main__":
    main()
