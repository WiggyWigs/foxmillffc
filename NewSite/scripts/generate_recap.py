#!/usr/bin/env python3
"""
Generates the Current Season page's top section: two AI-written
narratives (Previous Weekend Recap, Game of the Week) plus six short
factual callouts. Designed to run as part of the same Tuesday
automation, right after ingest_csv.py.

NARRATIVES (AI-written):
  - "Previous Weekend Recap" — ALWAYS the closest-margin game of the
    most recently completed week. This is a fixed, deterministic pick
    (no AI judgment involved in WHICH game); the AI only writes the
    recap text.
  - "Game of the Week" — a preview of the most compelling UPCOMING
    matchup. There's no mechanical definition of "compelling" for a
    game that hasn't happened, so the AI both PICKS the matchup (per
    recap_criteria.json) and writes about it. Which game gets featured
    is a judgment call each week, not a fixed formula.

CALLOUTS (plain templated facts, no AI call — "just facts and numbers"
per how these were scoped):
  - Result of last week's featured Game of the Week pick
  - Any brand-new record set this week (Record Books / Rafters)
  - Current longest active winning streak
  - Current longest active losing streak
  - Biggest margin of victory this week
  - Highest-scoring individual player this week (needs player_lineups.json)
  - Lowest-scoring team this week

Designed to fail SOFTLY throughout: if any single piece can't be
computed (no data yet, an API error), that piece is just omitted
rather than blocking everything else. A missing callout is a minor
loss; failing the whole weekly pipeline over it is not a reasonable
trade.

Requires ANTHROPIC_API_KEY as an environment variable (set from a
GitHub Secret in the automated workflow).
"""

import json
import os
import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
STATS_PATH = DATA_DIR / "stats.json"
STATS_SNAPSHOT_PATH = DATA_DIR / "stats_previous_run.json"  # written by espn_pull.py before ingest overwrites stats.json
UPCOMING_MATCHUPS_PATH = DATA_DIR / "upcoming_matchups.json"
PLAYER_LINEUPS_PATH = DATA_DIR / "player_lineups.json"
RECAP_CRITERIA_PATH = SCRIPT_DIR / "recap_criteria.json"

MODEL = "claude-sonnet-5"
API_URL = "https://api.anthropic.com/v1/messages"

# Each Record Books / Rafters leaderboard, mapped to the field name
# that actually holds its ranking value (confirmed against
# ingest_csv.py's real output structure — not guessed).
RECORD_LIST_VALUE_FIELDS = {
    "top_avg_regular_season": "avg_score", "bottom_avg_regular_season": "avg_score",
    "top_regular_season_games": "score", "bottom_regular_season_games": "score",
    "top_playoff_games": "score", "bottom_playoff_games": "score",
    "top_winning_streaks": "streak", "top_losing_streaks": "streak",
    "top_over100_streaks": "streak", "top_under100_streaks": "streak",
    "fastest_to_25_wins": "games", "fastest_to_50_wins": "games",
    "fastest_to_25_losses": "games", "fastest_to_50_losses": "games",
}


# --- Config loading ---------------------------------------------------

def load_recap_criteria():
    """Edit recap_criteria.json directly to change selection criteria —
    no code changes needed, this file is re-read fresh every run."""
    if not RECAP_CRITERIA_PATH.exists():
        return {}
    with open(RECAP_CRITERIA_PATH) as f:
        return json.load(f)


def get_criteria_for_week(criteria, section, week):
    """Week-specific override if one exists for this section, else the
    section's default. `week` is an int; JSON keys are strings."""
    section_criteria = criteria.get(section, {})
    overrides = section_criteria.get("week_overrides", {})
    return overrides.get(str(week), section_criteria.get("default_criteria", ""))


# --- Claude API ---------------------------------------------------------

def call_claude(system_prompt, user_prompt, max_tokens=400):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    resp = requests.post(
        API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(block["text"] for block in data["content"] if block["type"] == "text").strip()


# --- Shared helpers -------------------------------------------------------

def week_num(w):
    return int(w) if str(w).isdigit() else 0


def get_week_games(stats):
    """All of the most recently completed week's games, with H2H
    context for each."""
    games = stats.get("games", [])
    if not games:
        return None, None, None

    current_year = max(g["year"] for g in games)
    season_games = [g for g in games if g["year"] == current_year and g["game_type"] == "Regular"]
    if not season_games:
        return None, None, None

    latest_week = max(week_num(g["week"]) for g in season_games)
    week_games = [g for g in season_games if week_num(g["week"]) == latest_week]

    enriched = []
    for g in week_games:
        away, home = g["away_manager"], g["home_manager"]
        h2h_games = [
            gg for gg in stats["games"]
            if {gg["away_manager"], gg["home_manager"]} == {away, home}
        ]
        enriched.append({
            "away_manager": away, "away_score": g["away_score"],
            "home_manager": home, "home_score": g["home_score"],
            "margin": round(g["score_diff"], 2),
            "all_time_meetings": len(h2h_games),
        })
    return enriched, latest_week, current_year


# --- Previous Weekend Recap (AI writes about a fixed, deterministic pick) --

def build_recap_prompt(closest_game, week, year):
    system = (
        "You write short, punchy fantasy football recap blurbs for a small "
        "12-manager home league's website. Tone: knowledgeable, a little "
        "playful, never mean-spirited. 2-4 sentences. Use ONLY the facts "
        "given — never invent player names, stats, or plays, since none "
        "are available. Do not use markdown formatting. Start your "
        "response with the two manager names in the format "
        "'ManagerA vs ManagerB: ' followed by the recap."
    )
    user = (
        f"Write a recap of the closest game of Week {week}, {year} — this "
        f"was the tightest matchup of the week by score margin:\n"
        f"{json.dumps(closest_game, indent=2)}\n\n"
        f"Mention the final score and margin. If all_time_meetings is more "
        f"than 1, you can briefly note this isn't their first meeting — "
        f"don't invent details about those past games beyond the count."
    )
    return system, user


# --- Game of the Week (AI both picks and writes) ---------------------------

def build_game_of_week_prompt(upcoming, stats, criteria):
    matchups = upcoming.get("matchups", [])
    if not matchups:
        return None, None

    standings = {}
    if stats.get("current_standings"):
        for row in stats["current_standings"]["standings"]:
            standings[row["manager"]] = row

    enriched = []
    for m in matchups:
        away, home = m["away_manager"], m["home_manager"]
        h2h_games = [
            g for g in stats["games"]
            if {g["away_manager"], g["home_manager"]} == {away, home}
        ]
        enriched.append({
            "away_manager": away,
            "away_record": standings.get(away, {}).get("wins"),
            "home_manager": home,
            "home_record": standings.get(home, {}).get("wins"),
            "all_time_meetings": len(h2h_games),
        })

    system = (
        "You pick the single most compelling upcoming matchup from a list "
        "for a small 12-manager fantasy football league's website, based "
        "on the selection criteria given, then write a short, engaging "
        "preview of it. Tone: knowledgeable, a little playful, never "
        "mean-spirited. 2-4 sentences. Use ONLY the facts given — never "
        "invent player names, projections, or stats not provided. Do not "
        "use markdown formatting. Start your response with the two "
        "manager names in the format 'ManagerA vs ManagerB: ' followed by "
        "the preview."
    )
    user = (
        f"Selection criteria: {criteria}\n\n"
        f"This week's matchups:\n{json.dumps(enriched, indent=2)}"
    )
    return system, user


def pick_game_of_week_matchup(gotw_text, upcoming):
    """Parses which matchup the AI actually picked out of its own
    response text (it's instructed to start with 'ManagerA vs
    ManagerB: '), so next week we can look up the real result. Falls
    back to None if parsing fails — the result callout just won't
    show up next week rather than showing something wrong."""
    if not gotw_text or " vs " not in gotw_text:
        return None
    try:
        header = gotw_text.split(":", 1)[0]
        a, b = [s.strip() for s in header.split(" vs ")]
        valid_managers = {m["away_manager"] for m in upcoming["matchups"]} | \
                          {m["home_manager"] for m in upcoming["matchups"]}
        if a in valid_managers and b in valid_managers:
            return {"manager_a": a, "manager_b": b,
                    "week": upcoming.get("week"), "year": upcoming.get("year")}
    except Exception:
        pass
    return None


# --- Callout: last week's featured Game of the Week, actual result --------

def callout_last_gotw_result(old_stats, new_games):
    old_pick = (old_stats or {}).get("weekly_recap", {}).get("game_of_the_week_matchup")
    if not old_pick:
        return None
    a, b = old_pick.get("manager_a"), old_pick.get("manager_b")
    year, week = old_pick.get("year"), old_pick.get("week")
    if not all([a, b, year, week]):
        return None

    match = next(
        (g for g in new_games
         if g["year"] == year and week_num(g["week"]) == week_num(week)
         and {g["away_manager"], g["home_manager"]} == {a, b}),
        None,
    )
    if not match:
        return None

    winner = match["winner"] or "Tie"
    return (f"Last week's Game of the Week — {a} vs {b} — went to {winner}, "
            f"{match['away_manager']} {match['away_score']} - "
            f"{match['home_score']} {match['home_manager']}.")


# --- Callout: new record set this week -------------------------------------

def detect_new_records(old_stats, new_stats):
    """Compares each Record Books / Rafters leaderboard's TOP entry
    (or tied-for-first group) before vs after this week's games. A
    change means a new record was set. Deliberately looks only at the
    top of each list — a shuffle further down isn't a new record."""
    if not old_stats:
        return []

    old_records = old_stats.get("records", {})
    new_records = new_stats.get("records", {})
    callouts = []

    for key, value_field in RECORD_LIST_VALUE_FIELDS.items():
        old_list = old_records.get(key) or []
        new_list = new_records.get(key) or []
        if not new_list or not old_list:
            continue  # nothing to compare, or list is new itself — not a "new record"

        new_top_value = new_list[0][value_field]
        old_top_value = old_list[0][value_field]
        new_top_managers = {e["manager"] for e in new_list if e[value_field] == new_top_value}
        old_top_managers = {e["manager"] for e in old_list if e[value_field] == old_top_value}

        newly_added = new_top_managers - old_top_managers
        if newly_added:
            names = ", ".join(sorted(newly_added))
            callouts.append(f"New entry atop {key.replace('_', ' ')}: {names}.")

    return callouts


# --- Callouts: streaks, margin, scores (straightforward data lookups) -----

def callout_streaks(stats):
    cs = stats.get("current_streaks")
    if not cs:
        return None, None

    win_callout = loss_callout = None
    if cs.get("top_current_winning_streaks"):
        top = cs["top_current_winning_streaks"]
        streak = top[0]["win_streak"]
        names = ", ".join(e["manager"] for e in top if e["win_streak"] == streak)
        win_callout = f"Longest active winning streak: {names} ({streak} games)."
    if cs.get("top_current_losing_streaks"):
        top = cs["top_current_losing_streaks"]
        streak = top[0]["loss_streak"]
        names = ", ".join(e["manager"] for e in top if e["loss_streak"] == streak)
        loss_callout = f"Longest active losing streak: {names} ({streak} games)."
    return win_callout, loss_callout


def callout_biggest_margin(week_games):
    if not week_games:
        return None
    biggest = max(week_games, key=lambda g: g["margin"])
    winner = biggest["away_manager"] if biggest["away_score"] > biggest["home_score"] else biggest["home_manager"]
    loser = biggest["home_manager"] if winner == biggest["away_manager"] else biggest["away_manager"]
    return (f"Biggest margin of victory: {winner} over {loser} by "
            f"{biggest['margin']} points.")


def callout_lowest_scoring_team(week_games):
    if not week_games:
        return None
    all_scores = []
    for g in week_games:
        all_scores.append((g["away_manager"], g["away_score"]))
        all_scores.append((g["home_manager"], g["home_score"]))
    manager, score = min(all_scores, key=lambda t: t[1])
    return f"Lowest team score of the week: {manager} with {score} points."


def callout_highest_scoring_player(year, week):
    if not PLAYER_LINEUPS_PATH.exists():
        return None
    with open(PLAYER_LINEUPS_PATH) as f:
        lineups = json.load(f)

    best = None
    for entry in lineups:
        if entry["year"] != str(year) or week_num(entry["week"]) != week_num(week):
            continue
        for p in entry["players"]:
            if not p.get("started"):
                continue
            if best is None or p["points"] > best["points"]:
                best = {"manager": entry["manager"], "player": p["name"],
                        "position": p["position"], "points": p["points"]}
    if best is None:
        return None
    return (f"Highest-scoring player: {best['player']} ({best['position']}), "
            f"started by {best['manager']}, with {best['points']} points.")


# --- Main ---------------------------------------------------------------

def main():
    if not STATS_PATH.exists():
        print("No stats.json found — skipping recap generation.")
        return

    with open(STATS_PATH) as f:
        stats = json.load(f)

    old_stats = None
    if STATS_SNAPSHOT_PATH.exists():
        with open(STATS_SNAPSHOT_PATH) as f:
            old_stats = json.load(f)

    criteria = load_recap_criteria()
    week_games, week, year = get_week_games(stats)

    recap_text = None
    gotw_text = None
    gotw_matchup = None

    # --- Previous Weekend Recap: always the closest game ---
    try:
        if week_games:
            closest_game = min(week_games, key=lambda g: g["margin"])
            system, user = build_recap_prompt(closest_game, week, year)
            recap_text = call_claude(system, user)
            print("Generated Previous Weekend Recap.")
        else:
            print("No completed games found — skipping recap.")
    except Exception as e:
        print(f"WARNING: recap generation failed: {e}")

    # --- Game of the Week: AI picks and writes ---
    upcoming = None
    try:
        if UPCOMING_MATCHUPS_PATH.exists():
            with open(UPCOMING_MATCHUPS_PATH) as f:
                upcoming = json.load(f)
            week_criteria = get_criteria_for_week(criteria, "game_of_the_week", upcoming.get("week"))
            system, user = build_game_of_week_prompt(upcoming, stats, week_criteria)
            if system:
                gotw_text = call_claude(system, user)
                gotw_matchup = pick_game_of_week_matchup(gotw_text, upcoming)
                print("Generated Game of the Week.")
            else:
                print("No upcoming matchups available — skipping Game of the Week.")
        else:
            print("No upcoming_matchups.json found — skipping Game of the Week.")
    except Exception as e:
        print(f"WARNING: Game of the Week generation failed: {e}")

    # --- Callouts: each independent, each fails softly on its own ---
    callouts = {}
    try:
        callouts["last_gotw_result"] = callout_last_gotw_result(old_stats, stats.get("games", []))
    except Exception as e:
        print(f"WARNING: last_gotw_result callout failed: {e}")

    try:
        callouts["new_records"] = detect_new_records(old_stats, stats)
    except Exception as e:
        print(f"WARNING: new_records callout failed: {e}")

    try:
        win_streak, loss_streak = callout_streaks(stats)
        callouts["longest_win_streak"] = win_streak
        callouts["longest_loss_streak"] = loss_streak
    except Exception as e:
        print(f"WARNING: streak callouts failed: {e}")

    try:
        callouts["biggest_margin"] = callout_biggest_margin(week_games)
    except Exception as e:
        print(f"WARNING: biggest_margin callout failed: {e}")

    try:
        callouts["lowest_scoring_team"] = callout_lowest_scoring_team(week_games)
    except Exception as e:
        print(f"WARNING: lowest_scoring_team callout failed: {e}")

    try:
        callouts["highest_scoring_player"] = callout_highest_scoring_player(year, week) if week else None
    except Exception as e:
        print(f"WARNING: highest_scoring_player callout failed: {e}")

    if recap_text is None and gotw_text is None and not any(callouts.values()):
        print("Nothing generated this run — leaving stats.json untouched.")
        return

    stats["weekly_recap"] = {
        "previous_weekend": recap_text,
        "game_of_the_week": gotw_text,
        "game_of_the_week_matchup": gotw_matchup,  # structured, for next week's result lookup
        "callouts": callouts,
    }
    with open(STATS_PATH, "w") as f:
        json.dump(stats, f, indent=2)
    print("Saved recap content to stats.json.")


if __name__ == "__main__":
    main()
