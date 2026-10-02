#!/usr/bin/env python3
"""
Player Cards: each manager's standings stamp and season badges.

Usage:
    python player_cards.py

Reads data/stats.json (the game log and current standings) and
data/player_lineups.json (for Superstar), and writes the result into
stats.json under "player_cards". espn_pull.py runs this after
capture_latest_lineups(), so the latest week's lineups are already on
disk. It can't live in ingest_csv.py, which runs before that capture.

Every badge is recomputed from the full regular-season game log on
every run, so there is no saved "who has which badge" state. That is
what makes a badge permanent once earned: the game that earned it is
always still in the log. It is also why a season's cards freeze on
their own once Week 14 is in: only regular-season games count, so
nothing after that changes them. Each season from FIRST_CARD_SEASON on
is recomputed, which keeps past seasons available for an archive page.

Badge rules (all regular season only, Weeks 1-14):
  Longest Win Streak - every manager's longest run of consecutive wins
                       this season (a tie ends the run). Shown at 1+.
                       Season only: unlike the site's streak displays,
                       it does not carry over from the previous season.
  Weekly High Score  - count of weeks with the league's top score.
                       Ties: everyone tied gets credit.
  Superstar          - count of weeks with the league's top-scoring
                       starter. Ties: everyone tied gets credit.
  Giant Killer       - Week 5 or later, using standings entering the
                       week: the loser was ranked 1st-5th and the
                       winner was ranked at least 5 spots below them.
  High Point Club    - scored 150 or more in a game.
  The Punisher       - won by more than 50 points.
  Ice Cold           - lost 5 games in a row (a tie ends the run).
  Businessman        - not computed yet (needs transaction data).
"""

import json
import os
import re
import sys
from pathlib import Path

from ingest_csv import load_roster, rank_season_games, _week_sort_key

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
STATS_PATH = DATA_DIR / os.environ.get("STATS_FILENAME", "stats.json")
PLAYER_LINEUPS_PATH = DATA_DIR / os.environ.get("PLAYER_LINEUPS_FILENAME", "player_lineups.json")

FIRST_CARD_SEASON = 2026
REGULAR_SEASON_WEEKS = 14

MIN_WIN_STREAK = 1
GIANT_KILLER_FIRST_WEEK = 5
GIANT_KILLER_MAX_LOSER_RANK = 5
GIANT_KILLER_RANK_GAP = 5
HIGH_POINT_CLUB_SCORE = 150
PUNISHER_MARGIN = 50
ICE_COLD_LOSSES = 5

# Display order on the card and in the pop-up.
BADGE_ORDER = [
    "longest_win_streak", "weekly_high_score", "superstar", "giant_killer",
    "high_point_club", "the_punisher", "ice_cold", "businessman",
]


def slugify(name):
    """'Eddie McCumiskey' -> 'eddie-mccumiskey'. Card images are named
    images/cards/<slug>-<year>.jpg."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _week(g):
    return int(g["week"])


def _side(g, mgr):
    """(own_score, opponent, opponent_score, result) from mgr's side."""
    if g["away_manager"] == mgr:
        own, opp, opp_score = g["away_score"], g["home_manager"], g["home_score"]
    else:
        own, opp, opp_score = g["home_score"], g["away_manager"], g["away_score"]
    if g["tie"]:
        result = "T"
    elif g["winner"] == mgr:
        result = "W"
    else:
        result = "L"
    return own, opp, opp_score, result


def _game_event(g, mgr):
    own, opp, opp_score, _ = _side(g, mgr)
    return {"week": _week(g), "opponent": opp,
            "manager_score": own, "opponent_score": opp_score}


def _runs(games, mgr, result):
    """Every maximal run of consecutive `result` games for mgr, as lists
    of games in week order. Any other result (including a tie) ends a
    run."""
    runs, current = [], []
    for g in games:
        if _side(g, mgr)[3] == result:
            current.append(g)
        else:
            if current:
                runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def _ranks_entering_each_week(season_games, roster_names, weeks):
    """{week: {manager: rank}} using only games from earlier weeks, so
    it is the standings as they stood going into that week."""
    out = {}
    for wk in weeks:
        prior = [g for g in season_games if _week(g) < wk]
        if not prior:
            continue
        rows = rank_season_games(prior, roster_names)
        out[wk] = {row["manager"]: i + 1 for i, row in enumerate(rows)}
    return out


def _top_starters_by_week(lineups, year, weeks):
    """{week: (top_points, [ {manager, player, position, points}, ... ])}
    for every week whose lineups were captured. Everyone tied for the top
    starter is included."""
    out = {}
    for wk in weeks:
        best, holders = None, []
        for entry in lineups:
            if entry["year"] != str(year) or str(entry["week"]) != str(wk):
                continue
            for p in entry["players"]:
                if not p.get("started"):
                    continue
                hit = {"manager": entry["manager"], "player": p["name"],
                       "position": p["position"], "points": p["points"]}
                if best is None or p["points"] > best:
                    best, holders = p["points"], [hit]
                elif p["points"] == best:
                    holders.append(hit)
        if holders:
            out[wk] = (best, holders)
    return out


def compute_season_cards(all_games, lineups, roster_names, year):
    season_games = sorted(
        (g for g in all_games if g["year"] == year and g["game_type"] == "Regular"),
        key=lambda g: _week_sort_key(g["week"]),
    )
    if not season_games:
        return None

    weeks = sorted({_week(g) for g in season_games})
    standings = rank_season_games(season_games, roster_names)
    managers = [row["manager"] for row in standings]
    games_by_mgr = {m: [g for g in season_games if m in (g["away_manager"], g["home_manager"])]
                    for m in managers}

    ranks_entering = _ranks_entering_each_week(season_games, roster_names, weeks)
    top_starters = _top_starters_by_week(lineups, year, weeks)

    top_score_by_week = {}
    for wk in weeks:
        scores = [s for g in season_games if _week(g) == wk
                  for s in (g["away_score"], g["home_score"])]
        top_score_by_week[wk] = max(scores)

    badges = {m: {} for m in managers}

    for m in managers:
        glist = games_by_mgr[m]

        # Longest Win Streak: the longest run; if two runs tie for
        # longest, the most recent one is the one shown.
        win_runs = _runs(glist, m, "W")
        if win_runs:
            longest = max(len(r) for r in win_runs)
            if longest >= MIN_WIN_STREAK:
                run = [r for r in win_runs if len(r) == longest][-1]
                badges[m]["longest_win_streak"] = {
                    "count": longest,
                    "earned_week": _week(run[MIN_WIN_STREAK - 1]),
                    "events": [_game_event(g, m) for g in run],
                }

        # Ice Cold: every run of 5+ losses. Earned at the 5th loss of
        # the first such run.
        cold_runs = [r for r in _runs(glist, m, "L") if len(r) >= ICE_COLD_LOSSES]
        if cold_runs:
            badges[m]["ice_cold"] = {
                "count": None,
                "earned_week": _week(cold_runs[0][ICE_COLD_LOSSES - 1]),
                "events": [{"start_week": _week(r[0]), "end_week": _week(r[-1]),
                            "length": len(r)} for r in cold_runs],
            }

        high_point, punisher, high_score = [], [], []
        for g in glist:
            own, opp, opp_score, result = _side(g, m)
            if own >= HIGH_POINT_CLUB_SCORE:
                high_point.append(_game_event(g, m))
            if result == "W" and own - opp_score > PUNISHER_MARGIN:
                ev = _game_event(g, m)
                ev["margin"] = round(own - opp_score, 2)
                punisher.append(ev)
            if own == top_score_by_week[_week(g)]:
                high_score.append(_game_event(g, m))

        if high_score:
            badges[m]["weekly_high_score"] = {
                "count": len(high_score), "earned_week": high_score[0]["week"],
                "events": high_score,
            }
        if high_point:
            badges[m]["high_point_club"] = {
                "count": None, "earned_week": high_point[0]["week"], "events": high_point,
            }
        if punisher:
            badges[m]["the_punisher"] = {
                "count": None, "earned_week": punisher[0]["week"], "events": punisher,
            }

    # Superstar
    for wk in weeks:
        if wk not in top_starters:
            continue
        _, holders = top_starters[wk]
        for h in holders:
            if h["manager"] not in badges:
                continue
            b = badges[h["manager"]].setdefault(
                "superstar", {"count": 0, "earned_week": wk, "events": []})
            b["count"] += 1
            b["events"].append({"week": wk, "player": h["player"],
                                "position": h["position"], "points": h["points"]})

    # Giant Killer
    for g in season_games:
        wk = _week(g)
        if wk < GIANT_KILLER_FIRST_WEEK or g["tie"] or wk not in ranks_entering:
            continue
        ranks = ranks_entering[wk]
        winner, loser = g["winner"], g["loser"]
        if winner not in ranks or loser not in ranks or winner not in badges:
            continue
        if (ranks[loser] <= GIANT_KILLER_MAX_LOSER_RANK
                and ranks[winner] - ranks[loser] >= GIANT_KILLER_RANK_GAP):
            ev = _game_event(g, winner)
            ev["manager_rank"] = ranks[winner]
            ev["opponent_rank"] = ranks[loser]
            b = badges[winner].setdefault(
                "giant_killer", {"count": None, "earned_week": wk, "events": []})
            b["events"].append(ev)

    cards = []
    for rank, row in enumerate(standings, start=1):
        m = row["manager"]
        cards.append({
            "manager": m,
            "slug": slugify(m),
            "team_name": row["team_name"],
            "rank": rank,
            "wins": row["wins"], "losses": row["losses"], "ties": row["ties"],
            "points_for": row["points_for"],
            "badges": [dict(id=bid, **badges[m][bid]) for bid in BADGE_ORDER if bid in badges[m]],
        })

    through_week = max(weeks)
    return {
        "season": year,
        "through_week": through_week,
        "regular_season_complete": through_week >= REGULAR_SEASON_WEEKS,
        "lineup_weeks_missing": [wk for wk in weeks if wk not in top_starters],
        "managers_in_league": len(managers),
        "cards": cards,
    }


def compute_player_cards(all_games, lineups, roster_names):
    years = sorted({g["year"] for g in all_games if g["year"] >= FIRST_CARD_SEASON})
    seasons = {}
    for year in years:
        season = compute_season_cards(all_games, lineups, roster_names, year)
        if season:
            seasons[str(year)] = season
    if not seasons:
        return None
    return {"current_season": str(max(years)), "seasons": seasons}


def main():
    if not STATS_PATH.exists():
        print("Player cards: no stats.json yet, skipping.")
        return
    with open(STATS_PATH) as f:
        stats = json.load(f)
    lineups = []
    if PLAYER_LINEUPS_PATH.exists():
        with open(PLAYER_LINEUPS_PATH) as f:
            lineups = json.load(f)
    else:
        print("Player cards: no player_lineups.json, Superstar will be empty.")

    cards = compute_player_cards(stats.get("games", []), lineups, load_roster())
    stats["player_cards"] = cards
    with open(STATS_PATH, "w") as f:
        json.dump(stats, f, indent=2)

    if not cards:
        print(f"Player cards: no seasons from {FIRST_CARD_SEASON} on yet.")
        return
    for year, season in cards["seasons"].items():
        earned = sum(len(c["badges"]) for c in season["cards"])
        missing = season["lineup_weeks_missing"]
        print(f"Player cards {year}: through Week {season['through_week']}, "
              f"{earned} badges across {len(season['cards'])} managers"
              + (f" (no lineups for weeks {missing}, Superstar skips them)" if missing else ""))


if __name__ == "__main__":
    sys.exit(main())
