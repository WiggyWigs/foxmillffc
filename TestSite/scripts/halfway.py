#!/usr/bin/env python3
"""
"The Halfway Point": a one-time Current Season section, published once
Week 7 (of 14) is in. Every figure comes from the game log and the data
files the weekly run already writes; nothing is AI-written.

Usage:
    python halfway.py

espn_pull.py runs this last, after player_cards.py (Rock Bottom and Dust
Off the Mantle read the season's badges) and after capture_team_moves()
(Big Spender and Steady as He Goes read team_moves.json). It writes
stats.json["halfway_point"] when the latest completed regular-season week
is HALFWAY_WEEK, and removes it in every other week, so the section shows
for exactly one publication.

Sections:
  Rise and fall      - past seasons: teams in the top 6 at the halfway
                       point that missed the playoffs (Biggest Fall, by
                       spots dropped), and teams outside the top 6 that
                       made them (Biggest Rise, by spots gained).
  Schedules Matter   - this season's hardest and easiest schedule so far
                       (power rankings' schedule difficulty), whether the
                       rest of their schedule is easier or harder (their
                       remaining opponents' average power ranking), and
                       how past playoff teams' full-season schedule
                       difficulty compares.
  Mid-season awards  - Most Consistent, Rock Bottom, Dust Off the Mantle,
                       Best Pickup, Big Spender, Steady as He Goes.
  Second-half outlook - remaining strength of schedule (remaining
                       opponents' current win %), and remaining games
                       between current top-6 teams and between the teams
                       ranked 9-12.
"""

import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from ingest_csv import (load_roster, rank_season_games, compute_power_rankings,
                        _week_sort_key, PLAYOFF_SPOTS, HALFWAY_WEEK)

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
STATS_PATH = DATA_DIR / os.environ.get("STATS_FILENAME", "stats.json")
PLAYER_LINEUPS_PATH = DATA_DIR / os.environ.get("PLAYER_LINEUPS_FILENAME", "player_lineups.json")
REMAINING_SCHEDULE_PATH = DATA_DIR / os.environ.get("REMAINING_SCHEDULE_FILENAME", "remaining_schedule.json")
TEAM_MOVES_PATH = DATA_DIR / os.environ.get("TEAM_MOVES_FILENAME", "team_moves.json")

# Schedule difficulty is actual win % minus breakdown win %. Past playoff
# teams over +5% had a favorable schedule; under -5% a difficult one.
SCHEDULE_THRESHOLD = 0.05
BOTTOM_GROUP_FIRST_RANK = 9      # "battle to avoid last": ranks 9-12
BEST_PICKUP_MIN_WEEKS = 2        # weeks on the roster after the add


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _ties(rows, key, best):
    """Every row sharing the best value of `key` (best = min or max)."""
    if not rows:
        return []
    target = best(r[key] for r in rows)
    return [r for r in rows if r[key] == target]


def _complete_years(all_games, before):
    return sorted({g["year"] for g in all_games
                   if g["game_type"] == "Championship" and g["year"] < before})


def _playoff_teams(all_games, year):
    return {m for g in all_games if g["year"] == year and g["game_type"] != "Regular"
            for m in (g["away_manager"], g["home_manager"])}


def rise_and_fall(all_games, current_year, roster):
    falls, rises = [], []
    for year in _complete_years(all_games, current_year):
        reg = [g for g in all_games if g["year"] == year and g["game_type"] == "Regular"]
        half = [r["manager"] for r in rank_season_games(
            [g for g in reg if _week_sort_key(g["week"]) <= HALFWAY_WEEK], roster)]
        final = [r["manager"] for r in rank_season_games(reg, roster)]
        playoff = _playoff_teams(all_games, year)
        for m in final:
            h, f = half.index(m) + 1, final.index(m) + 1
            if h <= PLAYOFF_SPOTS and m not in playoff:
                falls.append({"year": year, "manager": m, "half_rank": h, "final_rank": f, "spots": f - h})
            elif h > PLAYOFF_SPOTS and m in playoff:
                rises.append({"year": year, "manager": m, "half_rank": h, "final_rank": f, "spots": h - f})
    order = lambda e: (-e["spots"], e["year"], e["manager"])
    return {"falls": sorted(falls, key=order), "rises": sorted(rises, key=order)}


def schedules(all_games, current_year, roster, power, remaining):
    rows = power.get("rankings", []) if power else []
    if not rows:
        return None
    power_rank = {r["manager"]: i + 1 for i, r in enumerate(rows)}
    n = len(rows)
    midpoint = (n + 1) / 2

    def outlook(row):
        opps = [b if a == row["manager"] else a for wk in remaining
                for a, b in wk if row["manager"] in (a, b)]
        if not opps:
            return {"remaining_opponents": 0}
        avg = round(sum(power_rank[o] for o in opps if o in power_rank) / len(opps), 1)
        # Power rank 1 is the strongest team: a higher average is easier.
        trend = "easier" if avg > midpoint else "harder" if avg < midpoint else "about the same"
        return {"remaining_opponents": len(opps), "avg_opponent_power_rank": avg, "trend": trend}

    def entry(row):
        return {"manager": row["manager"], "schedule_difficulty": row["schedule_difficulty"], **outlook(row)}

    history = {"playoff_teams": 0, "favorable": 0, "difficult": 0, "threshold": SCHEDULE_THRESHOLD}
    lowest = None
    for year in _complete_years(all_games, current_year):
        playoff = _playoff_teams(all_games, year)
        past = compute_power_rankings([g for g in all_games if g["year"] <= year], roster) or {}
        for r in past.get("rankings", []):
            if r["manager"] not in playoff:
                continue
            sd = r["schedule_difficulty"]
            history["playoff_teams"] += 1
            history["favorable"] += sd > SCHEDULE_THRESHOLD
            history["difficult"] += sd < -SCHEDULE_THRESHOLD
            if lowest is None or sd < lowest["schedule_difficulty"]:
                lowest = {"manager": r["manager"], "year": year, "schedule_difficulty": sd}
    history["lowest_playoff"] = lowest
    history["below_lowest_now"] = ([{"manager": r["manager"], "schedule_difficulty": r["schedule_difficulty"]}
                                    for r in rows if r["schedule_difficulty"] < lowest["schedule_difficulty"]]
                                   if lowest else [])
    return {
        "hardest": [entry(r) for r in _ties(rows, "schedule_difficulty", min)],
        "easiest": [entry(r) for r in _ties(rows, "schedule_difficulty", max)],
        "teams": n,
        "history": history,
    }


def awards(season_games, year, roster, cards, lineups, moves):
    out = {}

    scores = defaultdict(list)
    for g in season_games:
        scores[g["away_manager"]].append(g["away_score"])
        scores[g["home_manager"]].append(g["home_score"])
    spread = [{"manager": m, "stdev": round(statistics.pstdev(s), 2), "average": round(sum(s) / len(s), 2)}
              for m, s in scores.items() if len(s) > 1]
    out["most_consistent"] = _ties(spread, "stdev", min)

    badge_rows = []
    for card in cards:
        bob = next((b for b in card["badges"] if b["id"] == "not_great_bob"), None)
        total = sum(b["count"] if isinstance(b.get("count"), int) else len(b.get("events", []))
                    for b in card["badges"])
        badge_rows.append({"manager": card["manager"], "badges": len(card["badges"]), "total": total,
                           "not_great_bob": len(bob["events"]) if bob else 0})
    bottom = [r for r in _ties(badge_rows, "not_great_bob", max) if r["not_great_bob"]]
    out["rock_bottom"] = [{"manager": r["manager"], "first_name": r["manager"].split()[0],
                           "count": r["not_great_bob"]} for r in bottom]
    most = _ties(badge_rows, "badges", max)
    most = _ties(most, "total", max)  # tiebreak: total badge count, numbers included
    out["mantle"] = [{"manager": r["manager"], "badges": r["badges"], "total": r["total"]}
                     for r in most if r["badges"]]

    stints = defaultdict(list)  # (manager, player_id) -> weekly points after the add
    names = {}
    for entry in lineups:
        if entry["year"] != str(year) or _week_sort_key(entry["week"]) > HALFWAY_WEEK:
            continue
        for p in entry["players"]:
            if p.get("waiver_pickup") is True:
                key = (entry["manager"], p.get("player_id") or p["name"])
                stints[key].append(p["points"])
                names[key] = (p["name"], p.get("position"))
    pickups = [{"manager": m, "player": names[(m, pid)][0], "position": names[(m, pid)][1],
                "average": round(sum(pts) / len(pts), 2), "weeks": len(pts)}
               for (m, pid), pts in stints.items() if len(pts) >= BEST_PICKUP_MIN_WEEKS]
    out["best_pickup"] = _ties(pickups, "average", max)

    teams = (moves or {}).get("managers", {}) if (moves or {}).get("year") == year else {}
    spend = [{"manager": m, "faab_spent": v["faab_spent"]} for m, v in teams.items()]
    out["big_spender"] = [r for r in _ties(spend, "faab_spent", max) if r["faab_spent"]]
    moved = [{"manager": m, "moves": v["acquisitions"] + v["trades"],
              "acquisitions": v["acquisitions"], "trades": v["trades"]} for m, v in teams.items()]
    out["steady"] = _ties(moved, "moves", min)
    out["moves_as_of_today"] = bool((moves or {}).get("as_of_today"))
    return out


def second_half(season_games, roster, remaining):
    standings = rank_season_games(season_games, roster)
    rank = {r["manager"]: i + 1 for i, r in enumerate(standings)}
    played = {r["manager"]: r["wins"] + r["losses"] + r["ties"] for r in standings}
    win_pct = {r["manager"]: (r["wins"] / played[r["manager"]] if played[r["manager"]] else 0.0)
               for r in standings}

    sos = []
    for m in rank:
        opps = [b if a == m else a for wk in remaining for a, b in wk if m in (a, b)]
        if opps:
            sos.append({"manager": m, "opponent_win_pct": round(sum(win_pct.get(o, 0) for o in opps) / len(opps), 3),
                        "games": len(opps)})
    sos.sort(key=lambda r: (-r["opponent_win_pct"], r["manager"]))

    def games_between(low, high):
        out = []
        for i, wk in enumerate(remaining):
            for a, b in wk:
                if low <= rank.get(a, 99) <= high and low <= rank.get(b, 99) <= high:
                    out.append({"week": HALFWAY_WEEK + 1 + i, "away": a, "away_rank": rank[a],
                                "home": b, "home_rank": rank[b]})
        return out

    n = len(rank)
    return {
        "strength_of_schedule": sos,
        "top_games": games_between(1, PLAYOFF_SPOTS),
        "bottom_games": games_between(BOTTOM_GROUP_FIRST_RANK, n) if n >= BOTTOM_GROUP_FIRST_RANK else [],
        "bottom_first_rank": BOTTOM_GROUP_FIRST_RANK,
        "teams": n,
    }


def compute_halfway(stats, lineups, remaining_file, moves, roster):
    games = stats.get("games", [])
    regular = [g for g in games if g["game_type"] == "Regular"]
    if not regular:
        return None
    year = max(g["year"] for g in regular)
    season = [g for g in regular if g["year"] == year]
    if max(_week_sort_key(g["week"]) for g in season) != HALFWAY_WEEK:
        return None
    remaining = []
    if (remaining_file or {}).get("year") == year:
        weeks = remaining_file.get("weeks", {})
        remaining = [[(m["away_manager"], m["home_manager"]) for m in weeks[w]]
                     for w in sorted(weeks, key=int) if int(w) > HALFWAY_WEEK]
    cards = (stats.get("player_cards", {}).get("seasons", {}).get(str(year), {}) or {}).get("cards", [])
    return {
        "season": year,
        "week": HALFWAY_WEEK,
        "rise_and_fall": rise_and_fall(games, year, roster),
        "schedules": schedules(games, year, roster, stats.get("power_rankings"), remaining),
        "awards": awards(season, year, roster, cards, lineups, moves),
        "second_half": second_half(season, roster, remaining),
    }


def main():
    stats = _load(STATS_PATH, None)
    if not stats:
        sys.exit(f"{STATS_PATH} not found")
    halfway = compute_halfway(stats, _load(PLAYER_LINEUPS_PATH, []), _load(REMAINING_SCHEDULE_PATH, None),
                              _load(TEAM_MOVES_PATH, None), load_roster())
    if halfway:
        stats["halfway_point"] = halfway
        print(f"The Halfway Point: written for {halfway['season']} Week {halfway['week']}.")
    else:
        stats.pop("halfway_point", None)
        print("The Halfway Point: not the halfway week, section left out.")
    with open(STATS_PATH, "w") as f:
        json.dump(stats, f, indent=2)


if __name__ == "__main__":
    main()
