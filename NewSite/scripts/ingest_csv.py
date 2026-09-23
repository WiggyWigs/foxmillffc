#!/usr/bin/env python3
"""
Fantasy Football League - CSV ingestion script.

Usage:
    python ingest_csv.py path/to/weekly_or_historical.csv

Reads a CSV with columns:
    Year, Week, Away Team, Home Team, Away Score, Home Score, Away Manager, Home Manager

Week values are either an integer 1-14 (regular season) or "P1"/"P2"/"P3" (playoffs:
quarterfinal / semifinal / championship, with two teams receiving a bye into P2).

Appends new games to data/stats.json's game log (skipping rows already ingested),
then fully recomputes every manager's season and career stats from the complete
game log. Nothing is hand-edited or incrementally patched — every run derives
career stats from scratch from the raw games, so a corrected historical score
propagates everywhere automatically.

All manager names are validated against data/manager_roster.json. An unrecognized
name is a hard error, not a silently-created new manager — this is the guardrail
against manager-name typos fragmenting career stats.
"""

import csv
import os
import json
import sys
from pathlib import Path
from datetime import date
from collections import defaultdict
from fractions import Fraction

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
ROSTER_PATH = DATA_DIR / "manager_roster.json"
STATS_PATH = DATA_DIR / os.environ.get("STATS_FILENAME", "stats.json")
REMAINING_SCHEDULE_PATH = DATA_DIR / os.environ.get("REMAINING_SCHEDULE_FILENAME", "remaining_schedule.json")
ASSETS_DIR = SCRIPT_DIR.parent / "assets"
BANNER_BLANK_PATH = ASSETS_DIR / "banner_blank_25wins.png"
BANNER_OUTPUT_PATH = DATA_DIR / os.environ.get("BANNER_FILENAME", "fastest-to-25-wins-banner.png")  # local working copy only —
# on the live site this file belongs in NewSite/images/, NOT NewSite/data/,
# since the-rafters.html references it as "images/fastest-to-25-wins-banner.png".
BANNER_FONT_PATH = ASSETS_DIR / "BigShoulders-Bold.ttf"

REGULAR_SEASON_WEEKS = {str(w) for w in range(1, 15)}
PLAYOFF_GAME_TYPES = {"P1": "Quarterfinal", "P2": "Semifinal", "P3": "Championship"}


def load_json(path, default):
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return default


def load_roster():
    roster = load_json(ROSTER_PATH, None)
    if roster is None:
        sys.exit(f"ERROR: {ROSTER_PATH} not found. Create it before running ingestion.")
    names = set(roster["managers"])
    if any(n.startswith("REPLACE_ME") for n in names):
        sys.exit(
            "ERROR: manager_roster.json still contains placeholder names. "
            "Replace all REPLACE_ME_Manager_N entries with your real manager names first."
        )
    return names


def parse_week(raw_week):
    """Returns (week_key: str, game_type: str)."""
    w = str(raw_week).strip()
    if w in PLAYOFF_GAME_TYPES:
        return w, PLAYOFF_GAME_TYPES[w]
    if w in REGULAR_SEASON_WEEKS:
        return w, "Regular"
    sys.exit(f"ERROR: unrecognized Week value '{raw_week}'. Expected 1-14 or P1/P2/P3.")


def build_game(row, roster_names):
    away_mgr = row["Away Manager"].strip()
    home_mgr = row["Home Manager"].strip()
    for mgr in (away_mgr, home_mgr):
        if mgr not in roster_names:
            print(
                f"WARNING: manager '{mgr}' not found in manager_roster.json "
                f"(Year {row['Year']}, Week {row['Week']}). Ingesting anyway, but "
                f"this manager will NOT appear correctly on the Manager Score Index "
                f"until you add them to the roster or fix the name."
            )

    year = int(row["Year"])
    week_key, game_type = parse_week(row["Week"])
    away_score = float(row["Away Score"])
    home_score = float(row["Home Score"])

    tie = away_score == home_score
    if tie:
        winner, loser = None, None
    elif away_score > home_score:
        winner, loser = away_mgr, home_mgr
    else:
        winner, loser = home_mgr, away_mgr

    return {
        "year": year,
        "week": week_key,
        "game_type": game_type,
        "away_team": row["Away Team"].strip(),
        "home_team": row["Home Team"].strip(),
        "away_manager": away_mgr,
        "home_manager": home_mgr,
        "away_score": away_score,
        "home_score": home_score,
        "winner": winner,
        "loser": loser,
        "tie": tie,
        "score_diff": round(abs(away_score - home_score), 2),
        "combined_total": round(away_score + home_score, 2),
    }


def game_key(g):
    """Unique identity for de-duplication across repeated ingestion runs."""
    return (g["year"], g["week"], g["away_manager"], g["home_manager"])


def ingest_new_games(csv_path, existing_games, roster_names):
    existing_keys = {game_key(g) for g in existing_games}
    new_games = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            game = build_game(row, roster_names)
            if game_key(game) in existing_keys:
                continue  # already ingested, skip silently
            new_games.append(game)
            existing_keys.add(game_key(game))
    return existing_games + new_games


def recompute_stats(all_games, roster_names):
    """Fully rebuilds season and career stats from the raw game log."""
    seasons = defaultdict(lambda: defaultdict(lambda: {
        "regular_wins": 0, "regular_losses": 0, "regular_ties": 0,
        "playoff_wins": 0, "playoff_losses": 0, "playoff_ties": 0,
        "points_for_regular": 0.0, "points_for_total": 0.0, "points_against": 0.0,
        "made_playoffs": False, "playoff_finish": None,
        "champion": False, "points_title": False,
        "weekly_high_scores": 0, "weekly_low_scores": 0,
    }))

    # --- Pass 1: wins/losses/ties, points, playoff/championship flags ---
    for g in all_games:
        year = g["year"]
        for side_mgr, own_score, opp_score in (
            (g["away_manager"], g["away_score"], g["home_score"]),
            (g["home_manager"], g["home_score"], g["away_score"]),
        ):
            s = seasons[side_mgr][year]
            s["points_for_total"] += own_score
            s["points_against"] += opp_score
            is_regular = g["game_type"] == "Regular"
            if is_regular:
                s["points_for_regular"] += own_score

            bucket = "regular" if is_regular else "playoff"
            if g["tie"]:
                s[f"{bucket}_ties"] += 1
            elif g["winner"] == side_mgr:
                s[f"{bucket}_wins"] += 1
            else:
                s[f"{bucket}_losses"] += 1

            if not is_regular:
                s["made_playoffs"] = True
                if g["game_type"] == "Championship" and g["winner"] == side_mgr:
                    s["champion"] = True
                    s["playoff_finish"] = "Champion"
                elif g["game_type"] == "Championship":
                    if s["playoff_finish"] is None:
                        s["playoff_finish"] = "Runner-up"

    # --- Pass 2: regular-season weekly high/low (ties get credit to all) ---
    week_scores = defaultdict(list)  # (year, week) -> [(manager, score), ...]
    for g in all_games:
        if g["game_type"] != "Regular":
            continue
        week_scores[(g["year"], g["week"])].append((g["away_manager"], g["away_score"]))
        week_scores[(g["year"], g["week"])].append((g["home_manager"], g["home_score"]))

    for (year, week), entries in week_scores.items():
        scores = [s for _, s in entries]
        hi, lo = max(scores), min(scores)
        for mgr, score in entries:
            if score == hi:
                seasons[mgr][year]["weekly_high_scores"] += 1
            if score == lo:
                seasons[mgr][year]["weekly_low_scores"] += 1

    # --- Pass 3: season points title (highest cumulative regular-season points_for) ---
    years = {g["year"] for g in all_games}
    for year in years:
        totals = {mgr: seasons[mgr][year]["points_for_regular"]
                  for mgr in roster_names if year in seasons[mgr]}
        if not totals:
            continue
        top = max(totals.values())
        for mgr, total in totals.items():
            if total == top:
                seasons[mgr][year]["points_title"] = True

    # --- Career rollups + Manager Score Index ---
    # MSI = 2*(playoff_apps/seasons) + 1.5*(regular_season_win_pct)
    #     + 1.3*(championships/seasons) + 1*(points_titles/seasons)
    #     + 0.8*(playoff_win_pct) + 0.5*(runner_ups/seasons)
    #
    # IMPORTANT: career totals (and therefore MSI) only fold in COMPLETE
    # seasons — ones with a recorded Championship game. An in-progress
    # season's partial record still gets its own seasons[year] entry
    # (other features may want it), but never feeds the career/MSI
    # rollup until that season's championship is actually in the log.
    complete_years = {g["year"] for g in all_games if g["game_type"] == "Championship"}

    managers_out = {}
    for mgr in roster_names:
        mgr_seasons = seasons.get(mgr, {})
        complete_mgr_seasons = {y: s for y, s in mgr_seasons.items() if y in complete_years}
        seasons_played = len(complete_mgr_seasons)

        career = {
            "regular_wins": 0, "regular_losses": 0, "regular_ties": 0,
            "playoff_wins": 0, "playoff_losses": 0, "playoff_ties": 0,
            "regular_season_win_pct": 0.0, "playoff_win_pct": 0.0,
            "seasons_played": seasons_played,
            "championships": 0, "playoff_appearances": 0, "points_titles": 0,
            "runner_ups": 0,
            "weekly_high_scores": 0, "weekly_low_scores": 0,
            "manager_score_index": 0.0,
        }
        for year, s in complete_mgr_seasons.items():
            career["regular_wins"] += s["regular_wins"]
            career["regular_losses"] += s["regular_losses"]
            career["regular_ties"] += s["regular_ties"]
            career["playoff_wins"] += s["playoff_wins"]
            career["playoff_losses"] += s["playoff_losses"]
            career["playoff_ties"] += s["playoff_ties"]
            career["championships"] += int(s["champion"])
            career["playoff_appearances"] += int(s["made_playoffs"])
            career["points_titles"] += int(s["points_title"])
            career["runner_ups"] += int(s["playoff_finish"] == "Runner-up")
            career["weekly_high_scores"] += s["weekly_high_scores"]
            career["weekly_low_scores"] += s["weekly_low_scores"]

        reg_decided = career["regular_wins"] + career["regular_losses"] + career["regular_ties"]
        career["regular_season_win_pct"] = (
            round(career["regular_wins"] / reg_decided, 4) if reg_decided else 0.0
        )
        po_decided = career["playoff_wins"] + career["playoff_losses"] + career["playoff_ties"]
        career["playoff_win_pct"] = (
            round(career["playoff_wins"] / po_decided, 4) if po_decided else 0.0
        )

        if seasons_played:
            msi = (
                2.0 * (career["playoff_appearances"] / seasons_played)
                + 1.5 * career["regular_season_win_pct"]
                + 1.3 * (career["championships"] / seasons_played)
                + 1.0 * (career["points_titles"] / seasons_played)
                + 0.8 * career["playoff_win_pct"]
                + 0.5 * (career["runner_ups"] / seasons_played)
            )
            career["manager_score_index"] = round(msi, 4)

        managers_out[mgr] = {
            "seasons": {str(y): s for y, s in sorted(mgr_seasons.items())},
            "career": career,
        }

    return managers_out


def _week_sort_key(week):
    """Chronological ordering within a season: 1-14, then P1, P2, P3."""
    w = str(week)
    if w.startswith("P"):
        return 100 + int(w[1:])
    return int(w)


def compute_records(all_games, roster_names):
    """
    Builds the Record Books data. Each record type is computed fresh from
    the raw game log every run — nothing here is hand-maintained, so a
    corrected historical score or a newly-added week automatically
    reshuffles every leaderboard on the next ingestion run.
    """
    years_present = {g["year"] for g in all_games}
    complete_years = {g["year"] for g in all_games if g["game_type"] == "Championship"}
    latest_year = max(years_present) if years_present else None
    # Only exclude the latest year if it's genuinely still in progress
    # (no championship recorded for it yet) — once it finishes, it's
    # historical like any other and should count normally.
    in_progress_year = latest_year if latest_year not in complete_years else None

    # --- Per-manager individual game entries (regular season & playoff) ---
    regular_entries = []  # {manager, year, week, score}
    playoff_entries = []
    games_above_125 = defaultdict(int)
    games_below_100 = defaultdict(int)
    total_games_played = defaultdict(int)

    for g in all_games:
        for mgr, score, team_name in ((g["away_manager"], g["away_score"], g["away_team"]),
                                       (g["home_manager"], g["home_score"], g["home_team"])):
            entry = {"manager": mgr, "team_name": team_name, "year": g["year"], "week": g["week"], "score": score}
            if g["game_type"] == "Regular":
                regular_entries.append(entry)
            else:
                playoff_entries.append(entry)
            # Unlike the old design, the in-progress season is now
            # INCLUDED here — expressing this as a rate (occurrences
            # divided by total games played) rather than a raw count
            # is what makes that fair: a manager 3 games into a new
            # season is compared on the same footing as one with 200
            # career games, rather than needing a full season before
            # showing up here at all.
            total_games_played[mgr] += 1
            if score > 125:
                games_above_125[mgr] += 1
            if score < 100:
                games_below_100[mgr] += 1

    top_regular_games = sorted(regular_entries, key=lambda e: -e["score"])[:15]
    bottom_regular_games = sorted(regular_entries, key=lambda e: e["score"])[:15]
    top_playoff_games = sorted(playoff_entries, key=lambda e: -e["score"])[:5]
    bottom_playoff_games = sorted(playoff_entries, key=lambda e: e["score"])[:5]

    # Smallest margins of victory, all-time — deliberately includes
    # the in-progress season's games (unlike games_above_125/below_100
    # above), since the whole point is to be able to tell whether a
    # game happening RIGHT NOW is a genuinely historic nail-biter.
    # Ties are excluded (a margin of 0 isn't a "narrow win").
    margin_entries = []
    for g in all_games:
        if g["tie"]:
            continue
        winner_score = max(g["away_score"], g["home_score"])
        loser_score = min(g["away_score"], g["home_score"])
        margin_entries.append({
            "winner": g["winner"], "loser": g["loser"],
            "winner_score": winner_score, "loser_score": loser_score,
            "margin": round(winner_score - loser_score, 2),
            "year": g["year"], "week": g["week"],
        })
    smallest_margins_sorted = sorted(margin_entries, key=lambda e: e["margin"])
    # Top-10-with-ties: pull in every game sharing the 10th-place margin
    # value, same "don't cut a tied group in half" principle used for
    # streaks below.
    if len(smallest_margins_sorted) <= 10:
        smallest_margins = smallest_margins_sorted
    else:
        cutoff = smallest_margins_sorted[9]["margin"]
        smallest_margins = [e for e in smallest_margins_sorted if e["margin"] <= cutoff]

    games_above_125_list = sorted(
        [{"manager": m, "count": c, "games_played": total_games_played[m],
          "rate": round(c / total_games_played[m], 4)} for m, c in games_above_125.items()],
        key=lambda e: -e["rate"],
    )
    games_below_100_list = sorted(
        [{"manager": m, "count": c, "games_played": total_games_played[m],
          "rate": round(c / total_games_played[m], 4)} for m, c in games_below_100.items()],
        key=lambda e: -e["rate"],
    )

    # --- Per-manager, per-season regular-season averages ---
    season_totals = defaultdict(lambda: defaultdict(lambda: {"total": 0.0, "games": 0}))
    for g in all_games:
        if g["game_type"] != "Regular":
            continue
        for mgr, score in ((g["away_manager"], g["away_score"]),
                           (g["home_manager"], g["home_score"])):
            season_totals[mgr][g["year"]]["total"] += score
            season_totals[mgr][g["year"]]["games"] += 1

    season_avgs = []
    MIN_GAMES_FOR_CURRENT_SEASON_AVG = 3
    for mgr, years in season_totals.items():
        for year, d in years.items():
            if not d["games"]:
                continue
            # The current in-progress season needs a real sample
            # before its average means anything — 1-2 games isn't a
            # season average, it's just whatever happened so far.
            # Complete (past) seasons have no such restriction, since
            # a finished season's average is always meaningful.
            if year == in_progress_year and d["games"] < MIN_GAMES_FOR_CURRENT_SEASON_AVG:
                continue
            season_avgs.append({
                "manager": mgr, "year": year,
                "avg_score": round(d["total"] / d["games"], 2),
            })

    top_avg_regular_season = sorted(season_avgs, key=lambda e: -e["avg_score"])[:10]
    bottom_avg_regular_season = sorted(season_avgs, key=lambda e: e["avg_score"])[:10]

    # --- Fastest to N wins / losses ---
    # Every game (regular + playoff) counts toward "games it took", in
    # true chronological order per manager. Ties count as a game played
    # but move neither the win nor the loss counter.
    manager_games = defaultdict(list)
    for g in all_games:
        for mgr in (g["away_manager"], g["home_manager"]):
            manager_games[mgr].append(g)

    milestones = {
        "fastest_to_25_wins": [], "fastest_to_50_wins": [],
        "fastest_to_25_losses": [], "fastest_to_50_losses": [],
    }

    for mgr, glist in manager_games.items():
        glist_sorted = sorted(glist, key=lambda g: (g["year"], _week_sort_key(g["week"])))
        wins = losses = games_played = 0
        hit_25w = hit_50w = hit_25l = hit_50l = False
        for g in glist_sorted:
            games_played += 1
            team_name = g["away_team"] if g["away_manager"] == mgr else g["home_team"]
            if g["tie"]:
                pass
            elif g["winner"] == mgr:
                wins += 1
            else:
                losses += 1

            if wins >= 25 and not hit_25w:
                milestones["fastest_to_25_wins"].append({
                    "manager": mgr, "team_name": team_name, "games": games_played,
                    "year": g["year"], "week": g["week"],
                })
                hit_25w = True
            if wins >= 50 and not hit_50w:
                milestones["fastest_to_50_wins"].append({
                    "manager": mgr, "team_name": team_name, "games": games_played,
                    "year": g["year"], "week": g["week"],
                })
                hit_50w = True
            if losses >= 25 and not hit_25l:
                milestones["fastest_to_25_losses"].append({
                    "manager": mgr, "team_name": team_name, "games": games_played,
                    "year": g["year"], "week": g["week"],
                })
                hit_25l = True
            if losses >= 50 and not hit_50l:
                milestones["fastest_to_50_losses"].append({
                    "manager": mgr, "team_name": team_name, "games": games_played,
                    "year": g["year"], "week": g["week"],
                })
                hit_50l = True

    for key in milestones:
        milestones[key].sort(key=lambda e: e["games"])

    # --- Longest regular-season winning/losing streaks, AND longest/
    # shortest streaks of scoring over/under 100 points ---
    # Playoff games are skipped entirely (not counted, not treated as a
    # break) — a Week 14 win followed by a playoff loss followed by
    # Week 1 of the next season is one continuous streak, per the rule
    # that only regular-season results matter here. A tie breaks both
    # a winning streak and a losing streak, since it's neither. A score
    # of exactly 100 counts as "over" (score >= 100), not a dead zone —
    # every game is unambiguously one bucket or the other.
    win_streaks = []
    loss_streaks = []
    over100_streaks = []
    under100_streaks = []

    for mgr, glist in manager_games.items():
        reg_games = [g for g in glist if g["game_type"] == "Regular"]
        reg_games.sort(key=lambda g: (g["year"], _week_sort_key(g["week"])))

        cur_win = cur_loss = 0
        win_start = loss_start = None
        best_win = best_loss = 0
        best_win_span = best_loss_span = None
        best_win_team = best_loss_team = None

        cur_over = cur_under = 0
        over_start = under_start = None
        best_over = best_under = 0
        best_over_span = best_under_span = None

        for g in reg_games:
            point = (g["year"], g["week"])
            team_name = g["away_team"] if g["away_manager"] == mgr else g["home_team"]
            if g["tie"]:
                cur_win = 0
                cur_loss = 0
            elif g["winner"] == mgr:
                if cur_win == 0:
                    win_start = point
                cur_win += 1
                cur_loss = 0
                if cur_win > best_win:
                    best_win = cur_win
                    best_win_span = (win_start, point)
                    best_win_team = team_name
            else:
                if cur_loss == 0:
                    loss_start = point
                cur_loss += 1
                cur_win = 0
                if cur_loss > best_loss:
                    best_loss = cur_loss
                    best_loss_span = (loss_start, point)
                    best_loss_team = team_name

            score = g["away_score"] if g["away_manager"] == mgr else g["home_score"]
            if score >= 100:
                if cur_over == 0:
                    over_start = point
                cur_over += 1
                cur_under = 0
                if cur_over > best_over:
                    best_over = cur_over
                    best_over_span = (over_start, point)
            else:
                if cur_under == 0:
                    under_start = point
                cur_under += 1
                cur_over = 0
                if cur_under > best_under:
                    best_under = cur_under
                    best_under_span = (under_start, point)

        def fmt_span(span):
            (sy, sw), (ey, ew) = span
            if sy == ey:
                return f"{sy} Wk{sw}–Wk{ew}"
            return f"{sy} Wk{sw} – {ey} Wk{ew}"

        if best_win > 0:
            win_streaks.append({
                "manager": mgr, "team_name": best_win_team, "streak": best_win, "span": fmt_span(best_win_span),
                "end_year": best_win_span[1][0], "end_week": best_win_span[1][1],
            })
        if best_loss > 0:
            loss_streaks.append({
                "manager": mgr, "team_name": best_loss_team, "streak": best_loss, "span": fmt_span(best_loss_span),
                "end_year": best_loss_span[1][0], "end_week": best_loss_span[1][1],
            })
        # Over/under streaks are appended even at 0 — a manager who has
        # NEVER strung together even one qualifying game is a genuine,
        # if unglamorous, entry on the "shortest" leaderboard.
        over100_streaks.append({
            "manager": mgr, "streak": best_over,
            "span": fmt_span(best_over_span) if best_over > 0 else "—",
            "end_year": best_over_span[1][0] if best_over > 0 else None,
        })
        under100_streaks.append({
            "manager": mgr, "streak": best_under,
            "span": fmt_span(best_under_span) if best_under > 0 else "—",
            "end_year": best_under_span[1][0] if best_under > 0 else None,
        })

    def top_n_with_ties(items, n):
        """Top N by streak descending, but a tie AT the Nth position
        pulls in every manager sharing that value — never cuts a tied
        group in half."""
        ordered = sorted(items, key=lambda e: -e["streak"])
        if len(ordered) <= n:
            return ordered
        cutoff = ordered[n - 1]["streak"]
        result = ordered[:n]
        i = n
        while i < len(ordered) and ordered[i]["streak"] == cutoff:
            result.append(ordered[i])
            i += 1
        return result

    def bottom_n_with_ties(items, n):
        """Mirror of top_n_with_ties, ascending."""
        ordered = sorted(items, key=lambda e: e["streak"])
        if len(ordered) <= n:
            return ordered
        cutoff = ordered[n - 1]["streak"]
        result = ordered[:n]
        i = n
        while i < len(ordered) and ordered[i]["streak"] == cutoff:
            result.append(ordered[i])
            i += 1
        return result

    win_streaks.sort(key=lambda e: -e["streak"])
    loss_streaks.sort(key=lambda e: -e["streak"])
    top_win_streaks = win_streaks[:5]
    top_loss_streaks = loss_streaks[:5]

    top_over100_streaks = top_n_with_ties(over100_streaks, 5)
    bottom_over100_streaks = bottom_n_with_ties(over100_streaks, 5)
    top_under100_streaks = top_n_with_ties(under100_streaks, 5)
    bottom_under100_streaks = bottom_n_with_ties(under100_streaks, 5)

    return {
        "top_avg_regular_season": top_avg_regular_season,
        "bottom_avg_regular_season": bottom_avg_regular_season,
        "top_regular_season_games": top_regular_games,
        "bottom_regular_season_games": bottom_regular_games,
        "top_playoff_games": top_playoff_games,
        "bottom_playoff_games": bottom_playoff_games,
        "smallest_margins": smallest_margins,
        "games_above_125": games_above_125_list,
        "games_below_100": games_below_100_list,
        "top_winning_streaks": top_win_streaks,
        "top_losing_streaks": top_loss_streaks,
        "top_over100_streaks": top_over100_streaks,
        "bottom_over100_streaks": bottom_over100_streaks,
        "top_under100_streaks": top_under100_streaks,
        "bottom_under100_streaks": bottom_under100_streaks,
        **milestones,
    }


def compute_power_rankings(all_games, roster_names):
    """
    Power Rankings for the current season only (the highest year present
    in the game log — this rolls forward automatically each new season,
    nothing hardcoded). Regular-season games only: the breakdown-record
    concept requires every manager to have played the same week, which
    only holds in the regular season (playoffs have byes, fewer teams).

    Three factors, each independently ranked 1st-to-last among however
    many managers played this season, awarding N points to 1st down to
    1 point to last (N = number of active managers this season):
      - Win %              → highest wins the most points
      - Points Scored       → highest wins the most points
      - Schedule Difficulty → LOWEST value wins the most points, since
        a very negative (Actual W% - Breakdown W%) means the manager's
        real record undersold their scoring quality — i.e. a hard
        schedule — and that's the manager who should score highest here.

    Ties within a factor share the same point value; the next distinct
    value skips ahead accordingly (standard competition ranking).
    """
    years = {g["year"] for g in all_games}
    if not years:
        return None
    current_year = max(years)
    season_games = [g for g in all_games
                    if g["year"] == current_year and g["game_type"] == "Regular"]
    if not season_games:
        return None

    actual = defaultdict(lambda: {"wins": 0, "losses": 0, "ties": 0, "points": 0.0})
    week_scores = defaultdict(list)  # week -> [(manager, score), ...]

    for g in season_games:
        for mgr, own_score, opp_score in (
            (g["away_manager"], g["away_score"], g["home_score"]),
            (g["home_manager"], g["home_score"], g["away_score"]),
        ):
            actual[mgr]["points"] += own_score
            if g["tie"]:
                actual[mgr]["ties"] += 1
            elif g["winner"] == mgr:
                actual[mgr]["wins"] += 1
            else:
                actual[mgr]["losses"] += 1
        week_scores[g["week"]].append((g["away_manager"], g["away_score"]))
        week_scores[g["week"]].append((g["home_manager"], g["home_score"]))

    # Breakdown record: each week, compare every manager's score against
    # every OTHER manager who played that same week.
    breakdown = defaultdict(lambda: {"wins": 0, "losses": 0, "ties": 0})
    for week, entries in week_scores.items():
        for mgr, score in entries:
            for other_mgr, other_score in entries:
                if other_mgr == mgr:
                    continue
                if score > other_score:
                    breakdown[mgr]["wins"] += 1
                elif score < other_score:
                    breakdown[mgr]["losses"] += 1
                else:
                    breakdown[mgr]["ties"] += 1

    active_managers = [m for m in roster_names if m in actual]

    results = []
    for mgr in active_managers:
        a = actual[mgr]
        b = breakdown[mgr]
        a_decided = a["wins"] + a["losses"]
        actual_wp = (a["wins"] / a_decided) if a_decided else 0.0
        b_decided = b["wins"] + b["losses"]
        breakdown_wp = (b["wins"] / b_decided) if b_decided else 0.0

        results.append({
            "manager": mgr,
            "wins": a["wins"], "losses": a["losses"], "ties": a["ties"],
            "win_pct": round(actual_wp, 4),
            "points_scored": round(a["points"], 2),
            "breakdown_wins": b["wins"], "breakdown_losses": b["losses"],
            "breakdown_ties": b["ties"],
            "breakdown_win_pct": round(breakdown_wp, 4),
            "schedule_difficulty": round(actual_wp - breakdown_wp, 4),
        })

    def assign_points(items, key, ascending):
        """Points awarded = rank position among N managers, best gets N,
        worst gets 1. Ties SPLIT the points evenly across the tied
        range — e.g. two managers tied for 1st each get (12+11)/2=11.5,
        not both getting the full 12. This can produce fractional
        point values, which is expected."""
        ordered = sorted(items, key=lambda x: x[key], reverse=not ascending)
        n = len(ordered)
        points_map = {}
        i = 0
        while i < n:
            j = i
            while j + 1 < n and ordered[j + 1][key] == ordered[i][key]:
                j += 1
            # Tied group spans positions i..j (0-indexed); individual
            # point values in that range would be (n-i) down to (n-j).
            # Split = average of that consecutive range.
            avg_points = ((n - i) + (n - j)) / 2
            for k in range(i, j + 1):
                points_map[ordered[k]["manager"]] = avg_points
            i = j + 1
        return points_map

    win_pct_points = assign_points(results, "win_pct", ascending=False)
    points_scored_points = assign_points(results, "points_scored", ascending=False)
    schedule_points = assign_points(results, "schedule_difficulty", ascending=True)

    for r in results:
        r["win_pct_points"] = win_pct_points[r["manager"]]
        r["points_scored_points"] = points_scored_points[r["manager"]]
        r["schedule_difficulty_points"] = schedule_points[r["manager"]]
        r["power_score"] = round(r["win_pct_points"] + r["points_scored_points"]
                                  + r["schedule_difficulty_points"], 2)

    results.sort(key=lambda x: -x["power_score"])

    return {"season": current_year, "rankings": results}


def compute_current_streaks(all_games, roster_names):
    """
    Each active manager's CURRENT active regular-season streak — this
    DOES carry across the season boundary, same continuation rule as
    the Record Books historical streak record (playoffs are skipped
    entirely, not counted and not a break; a Week 14 win followed by a
    new season's Week 1 win is one continuous streak). "Active" means
    the manager has at least one game in the current season — someone
    who stepped away isn't shown with a stale streak from a prior year
    they're no longer playing in.
    """
    years = {g["year"] for g in all_games}
    if not years:
        return None
    current_year = max(years)

    reg_games = [g for g in all_games if g["game_type"] == "Regular"]
    active_this_season = {
        mgr for g in reg_games if g["year"] == current_year
        for mgr in (g["away_manager"], g["home_manager"])
    }

    by_mgr = defaultdict(list)
    for g in reg_games:
        by_mgr[g["away_manager"]].append(g)
        by_mgr[g["home_manager"]].append(g)

    entries = []
    for mgr in roster_names:
        if mgr not in active_this_season:
            continue
        glist = by_mgr.get(mgr)
        if not glist:
            continue
        # Full history, not season-filtered — this is what lets the
        # streak reach back across the season boundary.
        glist_desc = sorted(glist, key=lambda g: (g["year"], _week_sort_key(g["week"])), reverse=True)
        most_recent = glist_desc[0]

        win_streak = loss_streak = 0
        streak_games_desc = []  # collected most-recent-first, reversed below for display
        if not most_recent["tie"]:
            if most_recent["winner"] == mgr:
                for g in glist_desc:
                    if g["tie"] or g["winner"] != mgr:
                        break
                    win_streak += 1
                    streak_games_desc.append(g)
            else:
                for g in glist_desc:
                    if g["tie"] or g["winner"] == mgr:
                        break
                    loss_streak += 1
                    streak_games_desc.append(g)

        # Chronological order (oldest first) for display — the streak
        # started with the oldest game and ends with the most recent.
        streak_game_details = []
        for g in reversed(streak_games_desc):
            if g["away_manager"] == mgr:
                opponent, own_score, opp_score = g["home_manager"], g["away_score"], g["home_score"]
            else:
                opponent, own_score, opp_score = g["away_manager"], g["home_score"], g["away_score"]
            streak_game_details.append({
                "opponent": opponent, "manager_score": own_score, "opponent_score": opp_score,
                "year": g["year"], "week": g["week"],
            })

        entries.append({
            "manager": mgr, "win_streak": win_streak, "loss_streak": loss_streak,
            "streak_games": streak_game_details,
        })

    def top_two_distinct_values(items, key):
        """'Top 2 including ties' = every manager whose value matches
        either of the two highest DISTINCT values present — not simply
        the first two rows, which would arbitrarily cut a 3-way tie."""
        nonzero = [e for e in items if e[key] > 0]
        distinct_values = sorted({e[key] for e in nonzero}, reverse=True)[:2]
        return sorted(
            [e for e in nonzero if e[key] in distinct_values],
            key=lambda e: -e[key],
        )

    return {
        "season": current_year,
        "top_current_winning_streaks": top_two_distinct_values(entries, "win_streak"),
        "top_current_losing_streaks": top_two_distinct_values(entries, "loss_streak"),
    }


def compute_standings(all_games, roster_names):
    """
    Current-season regular-season standings: Team Name, Manager, Record,
    Points For, Points Against. Sorted by win % (ties don't count in the
    decided-games denominator, same convention as everywhere else on
    this site). Ties in win % break by:
      1. Head-to-head record *among just the tied managers* (not the
         manager's overall record — specifically how they did against
         each other).
      2. If no head-to-head games were played among the tied group, OR
         head-to-head is genuinely even, total points scored breaks it.

    For 3+-way ties: this is pure PAIRWISE resolution, not an aggregate
    "win % against the whole group" — that approach can wrongly produce
    a winner by summing a decisive result against a third manager on
    top of an unresolved pair. Every pair in the group must have a
    clear, decisive head-to-head result, AND those results must combine
    into a fully distinct ranking with no tied win-counts. If either
    condition fails anywhere in the group — one undetermined pair, or a
    circular result where win-counts still tie despite every pair being
    individually decisive — the ENTIRE group falls back to points
    scored, not just the ambiguous pair.
    """
    years = {g["year"] for g in all_games}
    if not years:
        return None
    current_year = max(years)
    season_games = [g for g in all_games
                    if g["year"] == current_year and g["game_type"] == "Regular"]
    if not season_games:
        return None

    per_mgr = {}
    h2h = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "losses": 0, "ties": 0}))

    for g in season_games:
        for mgr, own_score, opp_score, opp_mgr, team_name in (
            (g["away_manager"], g["away_score"], g["home_score"], g["home_manager"], g["away_team"]),
            (g["home_manager"], g["home_score"], g["away_score"], g["away_manager"], g["home_team"]),
        ):
            s = per_mgr.setdefault(mgr, {
                "wins": 0, "losses": 0, "ties": 0,
                "points_for": 0.0, "points_against": 0.0, "team_name": team_name,
            })
            s["team_name"] = team_name
            s["points_for"] += own_score
            s["points_against"] += opp_score
            if g["tie"]:
                s["ties"] += 1
                h2h[mgr][opp_mgr]["ties"] += 1
            elif g["winner"] == mgr:
                s["wins"] += 1
                h2h[mgr][opp_mgr]["wins"] += 1
            else:
                s["losses"] += 1
                h2h[mgr][opp_mgr]["losses"] += 1

    active_managers = [m for m in roster_names if m in per_mgr]
    for m in active_managers:
        s = per_mgr[m]
        decided = s["wins"] + s["losses"]
        s["win_pct"] = (s["wins"] / decided) if decided else 0.0

    ordered = sorted(active_managers, key=lambda m: -per_mgr[m]["win_pct"])

    # Group managers tied on win %, break each group internally.
    final_order = []
    i = 0
    while i < len(ordered):
        j = i
        while (j + 1 < len(ordered)
               and per_mgr[ordered[j + 1]]["win_pct"] == per_mgr[ordered[i]]["win_pct"]):
            j += 1
        group = ordered[i:j + 1]

        if len(group) == 1:
            final_order.extend(group)
        else:
            # Pure pairwise resolution — NOT an aggregate "win% against
            # the whole group" (that can paper over an unresolved pair
            # by summing in a decisive win against a third manager).
            # Every pair must have a clear, decisive head-to-head
            # winner, AND those decisive results must combine into a
            # fully distinct ranking with no ties in win-count. If
            # either condition fails anywhere in the group — one
            # undetermined pair, or a circular result where win-counts
            # tie despite every pair being individually decisive —
            # the ENTIRE group falls back to points scored, not just
            # the ambiguous pair.
            any_undetermined = False
            win_counts = {m: 0 for m in group}
            for idx1 in range(len(group)):
                for idx2 in range(idx1 + 1, len(group)):
                    m1, m2 = group[idx1], group[idx2]
                    rec = h2h[m1].get(m2, {"wins": 0, "losses": 0})
                    w1, l1 = rec["wins"], rec["losses"]
                    if w1 > l1:
                        win_counts[m1] += 1
                    elif l1 > w1:
                        win_counts[m2] += 1
                    else:
                        any_undetermined = True  # 0-0 (never played) or even split

            if any_undetermined or len(set(win_counts.values())) < len(group):
                sorted_group = sorted(group, key=lambda m: -per_mgr[m]["points_for"])
            else:
                sorted_group = sorted(group, key=lambda m: -win_counts[m])

            final_order.extend(sorted_group)

        i = j + 1

    standings = []
    for m in final_order:
        s = per_mgr[m]
        standings.append({
            "manager": m,
            "team_name": s["team_name"],
            "wins": s["wins"], "losses": s["losses"], "ties": s["ties"],
            "win_pct": round(s["win_pct"], 4),
            "points_for": round(s["points_for"], 2),
            "points_against": round(s["points_against"], 2),
        })

    return {"season": current_year, "standings": standings}


MIN_HISTORICAL_SAMPLES = 4  # below this, an exact bucket is too noisy to trust

# Tie-break adjustments for managers sharing the exact same record. Each pair
# of tied managers is compared on two factors; the bigger the gap, the bigger
# the swing, up to +/-5 percentage points per factor (+/-10 combined).
# A gap must EXCEED a threshold to earn its tier (a gap of exactly 15.00
# points earns nothing; 15.01 earns 1%).
TIE_POINTS_THRESHOLDS = [15, 30, 45, 60, 75]   # total points scored -> 1%..5%
TIE_SCHED_THRESHOLDS = [4, 7, 10, 13, 16]      # schedule-difficulty gap, in
                                               # percentage points -> 1%..5%


def _tier_pct(gap, thresholds):
    """Number of thresholds the gap strictly exceeds (0-5) == percentage points."""
    return sum(1 for t in thresholds if gap > t)


def compute_tie_adjustments(group):
    """
    group: entries sharing the same (wins, losses); each has "manager",
    "points_scored", and "schedule_difficulty" (a fraction, 0.215 = +21.5%).

    Every manager is compared head-to-head with every OTHER manager in the
    group. Each comparison earns +tier for the better side and -tier for the
    worse side (more points = better; lower schedule_difficulty = harder
    schedule = better). A manager's adjustment per factor is the average of
    their comparisons, so it is always within +/-5, and the adjustments
    across a group sum to zero. Returns {manager: (points_adj, sched_adj)}.
    """
    k = len(group)
    out = {}
    for e in group:
        pts_total = sched_total = 0.0
        for o in group:
            if o is e:
                continue
            pts_gap = round(e["points_scored"] - o["points_scored"], 2)
            pts_tier = _tier_pct(abs(pts_gap), TIE_POINTS_THRESHOLDS)
            pts_total += pts_tier if pts_gap > 0 else -pts_tier

            # lower schedule_difficulty is better -> flip the sign
            sched_gap = round((o["schedule_difficulty"] - e["schedule_difficulty"]) * 100, 4)
            sched_tier = _tier_pct(abs(sched_gap), TIE_SCHED_THRESHOLDS)
            sched_total += sched_tier if sched_gap > 0 else -sched_tier
        out[e["manager"]] = (pts_total / (k - 1), sched_total / (k - 1))
    return out


def _manager_week_by_week_records(season_games, week_range):
    """
    For one season's regular-season games, returns
    {manager: {week: (wins, losses)}} — cumulative record through each
    week. Ties don't move wins/losses but the week still counts as
    played.
    """
    by_week = defaultdict(list)
    for g in season_games:
        by_week[_week_sort_key(g["week"])].append(g)

    record = defaultdict(lambda: [0, 0])  # manager -> [wins, losses]
    out = defaultdict(dict)
    for wk in week_range:
        for g in by_week.get(wk, []):
            for mgr in (g["away_manager"], g["home_manager"]):
                if g["tie"]:
                    continue
                if g["winner"] == mgr:
                    record[mgr][0] += 1
                else:
                    record[mgr][1] += 1
        for mgr, (w, l) in record.items():
            out[mgr][wk] = (w, l)
    return out


# League structure (6-team playoff, 2 byes; 14-game regular season).
PLAYOFF_SPOTS = 6
REGULAR_SEASON_GAMES = 14


def compute_clinched_playoffs(records, games_played,
                              total_games=REGULAR_SEASON_GAMES, spots=PLAYOFF_SPOTS):
    """
    Which managers have mathematically clinched a playoff spot regardless
    of who plays whom, what anyone scores, or how tiebreakers resolve.

    records:      {manager: (wins, losses)} (ties are excluded, matching
                  the standings' win% convention)
    games_played: {manager: games played, ties included}

    For each manager X, assume the WORST case for X (loses every remaining
    game) and the BEST case for every rival Y (wins every remaining game).
    Any rival whose best-case win% is >= X's worst-case win% could finish
    at or above X — a tie counts against X, since tiebreakers (head-to-head,
    then points) can't be known in advance. X has clinched if at most
    (spots - 1) rivals could finish at or above them: X is then guaranteed
    a top-`spots` finish.

    This deliberately ignores the remaining schedule, so it is SOUND (never
    reports a false clinch) but not COMPLETE — e.g. two rivals who still
    have to play each other can't both win, and this bound can't see that.
    Fractions are used so win% comparisons are exact.
    """
    worst = {}
    best = {}
    for mgr, (w, l) in records.items():
        remaining = max(0, total_games - games_played.get(mgr, 0))
        worst[mgr] = Fraction(w, w + l + remaining) if (w + l + remaining) else Fraction(0)
        best[mgr] = Fraction(w + remaining, w + l + remaining) if (w + l + remaining) else Fraction(0)

    clinched = set()
    for mgr in records:
        can_catch = sum(1 for other in records
                        if other != mgr and best[other] >= worst[mgr])
        if can_catch <= spots - 1:
            clinched.add(mgr)
    return clinched


def compute_eliminated_playoffs(records, games_played,
                                total_games=REGULAR_SEASON_GAMES, spots=PLAYOFF_SPOTS):
    """
    Mirror of compute_clinched_playoffs: X is eliminated when at least
    `spots` rivals are guaranteed to finish STRICTLY above X's best case.
    X wins every remaining game; each rival loses every remaining game; any
    rival whose worst-case win% still beats X's best-case win% is locked
    above X. A tie is not counted as "above" (tiebreakers are unknown), so
    a manager is only eliminated once the math leaves no room at all.
    Schedule-blind, so sound but not complete (see _exact_playoff_status).
    """
    worst = {}
    best = {}
    for mgr, (w, l) in records.items():
        remaining = max(0, total_games - games_played.get(mgr, 0))
        denom = w + l + remaining
        worst[mgr] = Fraction(w, denom) if denom else Fraction(0)
        best[mgr] = Fraction(w + remaining, denom) if denom else Fraction(0)

    eliminated = set()
    for mgr in records:
        locked_above = sum(1 for other in records
                           if other != mgr and worst[other] > best[mgr])
        if locked_above >= spots:
            eliminated.add(mgr)
    return eliminated


# Exact scenario checking is 2^games outcomes, so it only runs when few
# enough games remain (18 games = 3 full weeks of 6 = 262,144 outcomes).
# Earlier in the season the schedule-blind bounds are used on their own.
MAX_EXACT_GAMES = 18


def load_remaining_schedule(managers, games_played, current_year, current_week,
                            total_games=REGULAR_SEASON_GAMES, path=None):
    """
    Loads and STRICTLY validates data/remaining_schedule.json. Returns a list
    of weeks (each a list of (manager_a, manager_b)) or None if the file is
    missing or anything about it is off — in which case the caller falls back
    to the schedule-blind bounds. Better no exact answer than one computed
    from a wrong schedule.

    Checks: same season; contains every week from current_week+1 through
    total_games; every week pairs each active manager exactly once; and each
    manager's number of scheduled games equals the games they have left.
    """
    path = path or REMAINING_SCHEDULE_PATH
    if not path.exists():
        return None

    def reject(reason):
        print(f"Remaining schedule ignored ({reason}); using schedule-blind clinch/elimination bounds.")
        return None

    try:
        with open(path) as f:
            data = json.load(f)
        if int(data.get("year", -1)) != int(current_year):
            return reject("wrong season")
        weeks = data.get("weeks", {})
        needed = [str(w) for w in range(current_week + 1, total_games + 1)]
        if any(w not in weeks for w in needed):
            return reject("missing weeks")

        managers = set(managers)
        out = []
        scheduled = defaultdict(int)
        for w in needed:
            seen = []
            pairs = []
            for m in weeks[w]:
                a, b = m["away_manager"], m["home_manager"]
                pairs.append((a, b))
                seen.extend([a, b])
            if sorted(seen) != sorted(managers):
                return reject(f"week {w} doesn't pair every manager exactly once")
            for mgr in seen:
                scheduled[mgr] += 1
            out.append(pairs)

        for mgr in managers:
            if scheduled[mgr] != max(0, total_games - games_played.get(mgr, 0)):
                return reject(f"{mgr}'s scheduled games don't match games remaining")
        return out
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as e:
        return reject(f"unreadable: {e}")


def _exact_playoff_status(records, schedule, targets, spots=PLAYOFF_SPOTS):
    """
    Exhaustively plays out every win/loss combination of the remaining games
    in `schedule` (list of weeks of (a, b) pairs) and, for each manager in
    `targets`, decides:
      clinched   - in EVERY outcome, at most spots-1 rivals finish at or
                   above them (ties counted against them)
      eliminated - in EVERY outcome at least `spots` rivals finish strictly
                   above them (ties are not counted as "above")
    Anyone who can both make and miss the field in some outcome is neither.

    Assumes every remaining game produces a winner (a tied game is
    practically impossible with two-decimal scoring). Past ties are handled:
    win% excludes ties, as the standings do. Unresolvable tiebreaks are
    treated as unresolved both ways, so a manager stuck in a tie for the last
    spot is reported as neither clinched nor eliminated.
    """
    names = list(records)
    idx = {m: i for i, m in enumerate(names)}
    n = len(names)
    games = [(idx[a], idx[b]) for week in schedule for (a, b) in week]

    remaining = [0] * n
    for a, b in games:
        remaining[a] += 1
        remaining[b] += 1
    base_w = [records[m][0] for m in names]
    denom = [records[m][0] + records[m][1] + remaining[i] for i, m in enumerate(names)]
    # pct[i][k]: win% if team i wins k of its remaining games. Identical
    # fractions give bit-identical floats (correctly rounded division), so
    # equality comparisons below are exact.
    pct = [[(base_w[i] + k) / denom[i] if denom[i] else 0.0 for k in range(remaining[i] + 1)]
           for i in range(n)]

    alive = {idx[m] for m in targets}
    can_miss = set()   # some outcome where they could finish outside the field
    can_make = set()   # some outcome where they could finish inside the field

    for mask in range(1 << len(games)):
        wins = [0] * n
        for g, (a, b) in enumerate(games):
            if (mask >> g) & 1:
                wins[a] += 1
            else:
                wins[b] += 1
        p = [pct[i][wins[i]] for i in range(n)]

        for x in list(alive):
            px = p[x]
            at_or_above = 0
            strictly_above = 0
            for y in range(n):
                if y == x:
                    continue
                if p[y] > px:
                    strictly_above += 1
                    at_or_above += 1
                elif p[y] == px:
                    at_or_above += 1
            if 1 + at_or_above > spots:
                can_miss.add(x)
            if 1 + strictly_above <= spots:
                can_make.add(x)
            if x in can_miss and x in can_make:
                alive.discard(x)   # undecided for sure; stop checking them
        if not alive:
            break

    clinched = {names[x] for x in alive if x not in can_miss}
    eliminated = {names[x] for x in alive if x not in can_make}
    return clinched, eliminated


def compute_playoff_status(records, games_played, schedule=None,
                           total_games=REGULAR_SEASON_GAMES, spots=PLAYOFF_SPOTS):
    """
    Returns (clinched, eliminated, method). Always runs the cheap,
    schedule-blind bounds first; if a validated remaining schedule is
    supplied and few enough games remain, follows up with the exact
    scenario check for everyone still undecided. method is "exact" or
    "bound".
    """
    clinched = compute_clinched_playoffs(records, games_played, total_games, spots)
    eliminated = compute_eliminated_playoffs(records, games_played, total_games, spots)
    method = "bound"

    if schedule:
        n_games = sum(len(week) for week in schedule)
        if n_games <= MAX_EXACT_GAMES:
            undecided = [m for m in records if m not in clinched and m not in eliminated]
            c2, e2 = _exact_playoff_status(records, schedule, undecided, spots)
            clinched |= c2
            eliminated |= e2
            method = "exact"
    return clinched, eliminated, method


def _all_time_score_margin_leaderboards(all_games):
    """
    Top/bottom-5 all-time individual regular-season scores, and top/bottom-5
    all-time margins of victory (ties excluded from margins). Used by
    compute_week_in_history below. Deliberately a SEPARATE computation from
    compute_records' similar top-15/bottom-15 lists rather than a refactor
    of that function — a little duplicated O(n) work, zero risk to the
    already-working Record Books.
    """
    score_entries = []
    for g in all_games:
        if g["game_type"] != "Regular":
            continue
        for mgr, score, team_name in ((g["away_manager"], g["away_score"], g["away_team"]),
                                       (g["home_manager"], g["home_score"], g["home_team"])):
            score_entries.append({"manager": mgr, "team_name": team_name, "year": g["year"],
                                   "week": g["week"], "score": score})
    top_scores = sorted(score_entries, key=lambda e: -e["score"])[:5]
    bottom_scores = sorted(score_entries, key=lambda e: e["score"])[:5]

    margin_entries = []
    for g in all_games:
        if g["game_type"] != "Regular" or g["tie"]:
            continue
        winner_score = max(g["away_score"], g["home_score"])
        loser_score = min(g["away_score"], g["home_score"])
        margin_entries.append({"winner": g["winner"], "loser": g["loser"],
                                "winner_score": winner_score, "loser_score": loser_score,
                                "margin": round(winner_score - loser_score, 2),
                                "year": g["year"], "week": g["week"]})
    smallest_margins = sorted(margin_entries, key=lambda e: e["margin"])[:5]
    largest_margins = sorted(margin_entries, key=lambda e: -e["margin"])[:5]
    return {"top_scores": top_scores, "bottom_scores": bottom_scores,
            "smallest_margins": smallest_margins, "largest_margins": largest_margins}


def _regular_games_at_week(all_games, week_num, before_year):
    """Every completed regular-season game at week_num, from years strictly
    before before_year — the historical candidate pool for "This Week in
    Club History," which never includes the current season."""
    return [g for g in all_games
            if g["game_type"] == "Regular"
            and _week_sort_key(g["week"]) == week_num
            and g["year"] < before_year]


def _game_margin(g):
    if g["tie"]:
        return 0.0
    return round(max(g["away_score"], g["home_score"]) - min(g["away_score"], g["home_score"]), 2)


def _score_in_leaderboard(mgr, score, year, week, leaderboard, n=5):
    """1-based rank if this exact (manager, year, week, score) is within
    the top-n of leaderboard, else None."""
    for i, e in enumerate(leaderboard[:n]):
        if e["manager"] == mgr and e["year"] == year and e["week"] == week and e["score"] == score:
            return i + 1
    return None


def _margin_in_leaderboard(winner, loser, year, week, leaderboard, n=5):
    for i, e in enumerate(leaderboard[:n]):
        if e["winner"] == winner and e["loser"] == loser and e["year"] == year and e["week"] == week:
            return i + 1
    return None


def _week_in_history_candidate(g, reason, detail=None):
    return {
        "year": g["year"], "week": g["week"],
        "away_manager": g["away_manager"], "away_team": g["away_team"], "away_score": g["away_score"],
        "home_manager": g["home_manager"], "home_team": g["home_team"], "home_score": g["home_score"],
        "winner": g["winner"], "loser": g["loser"], "tie": g["tie"],
        "margin": _game_margin(g),
        "selection_reason": reason,
        "selection_detail": detail or {},
    }


def _pick_by_score_leaderboard(pool, leaderboard, n=5):
    """Among pool games, is EITHER score one of the top/bottom-n on
    leaderboard? If several qualify, the one whose qualifying score has
    the best (lowest) rank wins; ties broken by most recent year."""
    best = None
    for g in pool:
        for side_mgr, side_score in ((g["away_manager"], g["away_score"]),
                                      (g["home_manager"], g["home_score"])):
            rank = _score_in_leaderboard(side_mgr, side_score, g["year"], g["week"], leaderboard, n)
            if rank is None:
                continue
            key = (rank, -g["year"])
            if best is None or key < best[0]:
                best = (key, g, {"manager": side_mgr, "score": side_score, "rank": rank})
    if best is None:
        return None, None
    return best[1], best[2]


def _pick_by_margin_leaderboard(pool, leaderboard, n=5):
    best = None
    for g in pool:
        if g["tie"]:
            continue
        rank = _margin_in_leaderboard(g["winner"], g["loser"], g["year"], g["week"], leaderboard, n)
        if rank is None:
            continue
        key = (rank, -g["year"])
        if best is None or key < best[0]:
            best = (key, g, {"rank": rank, "margin": _game_margin(g)})
    if best is None:
        return None, None
    return best[1], best[2]


def _pick_smallest_margin(pool):
    if not pool:
        return None
    decisive = [g for g in pool if not g["tie"]]
    candidates = decisive if decisive else pool
    return min(candidates, key=lambda g: (_game_margin(g), -g["year"]))


def _pick_largest_margin(pool):
    if not pool:
        return None
    decisive = [g for g in pool if not g["tie"]]
    candidates = decisive if decisive else pool
    return max(candidates, key=lambda g: (_game_margin(g), g["year"]))


def _select_week_in_history_week1(pool, lb):
    if not pool:
        return None
    g, detail = _pick_by_score_leaderboard(pool, lb["top_scores"][:1])  # THE all-time high, rank 1 only
    if g:
        return _week_in_history_candidate(g, "week1_all_time_high_score", detail)
    g, detail = _pick_by_score_leaderboard(pool, lb["top_scores"])
    if g:
        return _week_in_history_candidate(g, "all_time_top5_score", detail)
    g, detail = _pick_by_margin_leaderboard(pool, lb["smallest_margins"])
    if g:
        return _week_in_history_candidate(g, "all_time_top5_smallest_margin", detail)
    return _week_in_history_candidate(_pick_smallest_margin(pool), "week_smallest_margin")


def _select_week_in_history_weeks2_4(pool, lb):
    if not pool:
        return None
    g, detail = _pick_by_score_leaderboard(pool, lb["top_scores"])
    if g:
        return _week_in_history_candidate(g, "all_time_top5_score", detail)
    g, detail = _pick_by_margin_leaderboard(pool, lb["smallest_margins"])
    if g:
        return _week_in_history_candidate(g, "all_time_top5_smallest_margin", detail)
    g, detail = _pick_by_margin_leaderboard(pool, lb["largest_margins"])
    if g:
        return _week_in_history_candidate(g, "all_time_top5_largest_margin", detail)
    return _week_in_history_candidate(_pick_smallest_margin(pool), "week_smallest_margin")


def _select_week_in_history_week5(pool, all_games):
    """Rule 1 is a milestone check unique to week 5: did any week-5 game
    that season push its winner to 5-0, or its loser to 0-5, using that
    manager's ACTUAL record through week 5 of that specific season (not
    the all-time leaderboards)."""
    if not pool:
        return None
    for g in pool:
        year = g["year"]
        season_games = [gg for gg in all_games if gg["game_type"] == "Regular" and gg["year"] == year
                        and _week_sort_key(gg["week"]) <= 5]
        for mgr in (g["away_manager"], g["home_manager"]):
            wins = sum(1 for gg in season_games if not gg["tie"] and gg["winner"] == mgr)
            losses = sum(1 for gg in season_games if not gg["tie"] and gg["loser"] == mgr)
            if wins == 5 or losses == 5:
                return _week_in_history_candidate(g, "milestone_5_0_or_0_5",
                                                   {"manager": mgr, "wins": wins, "losses": losses})
    lb = _all_time_score_margin_leaderboards(all_games)
    g, detail = _pick_by_margin_leaderboard(pool, lb["smallest_margins"])
    if g:
        return _week_in_history_candidate(g, "all_time_top5_smallest_margin", detail)
    g, detail = _pick_by_margin_leaderboard(pool, lb["largest_margins"])
    if g:
        return _week_in_history_candidate(g, "all_time_top5_largest_margin", detail)
    return _week_in_history_candidate(_pick_smallest_margin(pool), "week_smallest_margin")


def _select_week_in_history_weeks6_9(pool, lb):
    if not pool:
        return None
    g, detail = _pick_by_score_leaderboard(pool, lb["top_scores"])
    if g:
        return _week_in_history_candidate(g, "all_time_top5_score", detail)
    g, detail = _pick_by_score_leaderboard(pool, lb["bottom_scores"])
    if g:
        return _week_in_history_candidate(g, "all_time_bottom5_score", detail)
    g, detail = _pick_by_margin_leaderboard(pool, lb["largest_margins"])
    if g:
        return _week_in_history_candidate(g, "all_time_top5_largest_margin", detail)
    return _week_in_history_candidate(_pick_smallest_margin(pool), "week_smallest_margin")


def _select_week_in_history_week10(all_games, current_year, roster_names):
    """Not a tiered pick — deterministic: whoever finished LAST in the
    final regular-season standings two seasons before the current one,
    and their week-10 game that season."""
    target_year = current_year - 2
    season_games = [g for g in all_games if g["game_type"] == "Regular" and g["year"] == target_year]
    if not season_games:
        return None
    standings = compute_standings(season_games, roster_names)
    if not standings or not standings.get("standings"):
        return None
    last_place_mgr = standings["standings"][-1]["manager"]

    week10_games = [g for g in season_games if _week_sort_key(g["week"]) == 10
                    and (g["away_manager"] == last_place_mgr or g["home_manager"] == last_place_mgr)]
    if not week10_games:
        return None
    g = week10_games[0]
    return _week_in_history_candidate(g, "last_place_two_seasons_ago", {
        "manager": last_place_mgr, "won": g["winner"] == last_place_mgr, "season": target_year,
        "final_record": (standings["standings"][-1]["wins"], standings["standings"][-1]["losses"]),
    })


def _wih_records_and_games_played_through(season_games, week_cutoff):
    """(wins, losses) and games-played-so-far for every manager, counting
    only games with week <= week_cutoff (ties excluded from win/loss, but
    still count as a game played — matches the standings convention)."""
    records = defaultdict(lambda: [0, 0])
    played = defaultdict(int)
    for g in season_games:
        if _week_sort_key(g["week"]) > week_cutoff:
            continue
        for mgr in (g["away_manager"], g["home_manager"]):
            played[mgr] += 1
        if g["tie"]:
            continue
        records[g["winner"]][0] += 1
        records[g["loser"]][1] += 1
    return {m: tuple(v) for m, v in records.items()}, dict(played)


def _wih_schedule_after(season_games, week_cutoff):
    """[(mgr_a, mgr_b), ...] per week for every week strictly after
    week_cutoff, in week order — the exact-check format
    compute_playoff_status expects."""
    by_week = defaultdict(list)
    for g in season_games:
        wk = _week_sort_key(g["week"])
        if wk > week_cutoff:
            by_week[wk].append((g["away_manager"], g["home_manager"]))
    return [by_week[wk] for wk in sorted(by_week)]


def _select_week_in_history_weeks11_14(pool, all_games, week_num, roster_names):
    """A win/loss in this week's games is a candidate if it was THE thing
    that pushed that manager from not-yet-clinched to clinched (or
    not-yet-eliminated to eliminated), using that season's ACTUAL
    (fully-known, since it's history) remaining schedule — reusing
    compute_playoff_status exactly as the live current-season page does."""
    if not pool:
        return None

    by_year = defaultdict(list)
    for g in pool:
        by_year[g["year"]].append(g)

    candidates = []
    for year, games in by_year.items():
        season_games = [g for g in all_games if g["game_type"] == "Regular" and g["year"] == year]
        active = [m for m in roster_names
                  if any(g["away_manager"] == m or g["home_manager"] == m for g in season_games)]
        if not active:
            continue

        total_games_this_season = max(
            (_week_sort_key(g["week"]) for g in season_games), default=0
        )

        records_before, played_before = _wih_records_and_games_played_through(season_games, week_num - 1)
        records_before = {m: records_before.get(m, (0, 0)) for m in active}
        played_before = {m: played_before.get(m, 0) for m in active}
        schedule_before = _wih_schedule_after(season_games, week_num - 1)
        clinched_before, eliminated_before, _ = compute_playoff_status(
            records_before, played_before, schedule_before, total_games=total_games_this_season
        )

        records_after, played_after = _wih_records_and_games_played_through(season_games, week_num)
        records_after = {m: records_after.get(m, (0, 0)) for m in active}
        played_after = {m: played_after.get(m, 0) for m in active}
        schedule_after = _wih_schedule_after(season_games, week_num)
        clinched_after, eliminated_after, _ = compute_playoff_status(
            records_after, played_after, schedule_after, total_games=total_games_this_season
        )

        newly_clinched = clinched_after - clinched_before
        newly_eliminated = eliminated_after - eliminated_before

        for g in games:
            if g["winner"] in newly_clinched:
                candidates.append((year, g, "clinched_playoffs", {"manager": g["winner"]}))
            if g["loser"] in newly_eliminated:
                candidates.append((year, g, "eliminated_playoffs", {"manager": g["loser"]}))

    if candidates:
        # Most recent year first; a clinch takes priority over an
        # elimination when both happened in the same week (rule 1 before
        # rule 2), matching the stated priority order.
        candidates.sort(key=lambda c: (-c[0], 0 if c[2] == "clinched_playoffs" else 1))
        _, g, reason, detail = candidates[0]
        return _week_in_history_candidate(g, reason, detail)

    return _week_in_history_candidate(_pick_smallest_margin(pool), "week_smallest_margin")


def _historical_playoff_odds_after_start(all_games, start_wins, start_losses, through_week, exclude_year):
    """
    Across every PAST season (year < exclude_year), what fraction of
    managers whose record was exactly start_wins-start_losses after
    `through_week` games went on to make the playoffs that season?
    Returns (percentage, sample_size); (None, 0) if no season in
    history has ever produced a qualifying manager.
    """
    years = sorted({g["year"] for g in all_games if g["year"] < exclude_year})
    qualifying = 0
    made_playoffs = 0
    for year in years:
        season_games = [g for g in all_games if g["year"] == year and g["game_type"] == "Regular"]
        if not season_games:
            continue
        weeks_played = {_week_sort_key(g["week"]) for g in season_games}
        if through_week not in weeks_played:
            continue  # this season never reached that week (shouldn't normally happen)

        records = defaultdict(lambda: [0, 0])
        for g in season_games:
            if _week_sort_key(g["week"]) > through_week or g["tie"]:
                continue
            records[g["winner"]][0] += 1
            records[g["loser"]][1] += 1

        playoff_managers = {
            g[side] for g in all_games if g["year"] == year and g["game_type"] != "Regular"
            for side in ("away_manager", "home_manager")
        }
        for mgr, (w, l) in records.items():
            if (w, l) == (start_wins, start_losses):
                qualifying += 1
                if mgr in playoff_managers:
                    made_playoffs += 1

    if qualifying == 0:
        return None, 0
    return round(100 * made_playoffs / qualifying, 1), qualifying


def compute_more_you_know(all_games, roster_names):
    """
    Selects this week's "The More You Know" fact for the Deep Dive
    section. Dispatches by the MOST RECENTLY COMPLETED week (not the
    week ahead, unlike compute_week_in_history) — this fact is about the
    season as it stands right now, not a preview of what's coming.
    Returns None if nothing is defined for this week yet, or there's no
    historical sample to compute from.
    """
    years = {g["year"] for g in all_games}
    if not years:
        return None
    current_year = max(years)
    current_season_games = [g for g in all_games
                            if g["year"] == current_year and g["game_type"] == "Regular"]
    if not current_season_games:
        return None
    last_completed_week = max(_week_sort_key(g["week"]) for g in current_season_games)

    if last_completed_week == 2:
        pct, sample_size = _historical_playoff_odds_after_start(all_games, 0, 3, 3, current_year)
        if pct is None:
            return None
        records = defaultdict(lambda: [0, 0])
        for g in current_season_games:
            if g["tie"]:
                continue
            records[g["winner"]][0] += 1
            records[g["loser"]][1] += 1
        on_watch = sorted(m for m, (w, l) in records.items() if (w, l) == (0, 2))
        return {
            "reason": "playoff_odds_after_0_3_start",
            "value": pct, "sample_size": sample_size, "on_watch_teams": on_watch,
        }

    return None  # Week 1, and weeks 3+, are TBD


def compute_week_in_history(all_games, roster_names):
    """
    Selects one game from a PRIOR season, at the SAME week number as the
    week ahead — one past the most recently completed week, so it pairs
    with the forward-looking Game of the Week section rather than the
    backward-looking Impact Game recap. If Week 6 just finished, this
    looks at history for Week 7, not Week 6.

    Selection rules vary by week range (see the _select_week_in_history_*
    helpers above). Returns None if there's no eligible candidate yet —
    e.g. this is the league's first time reaching that week number, the
    current season has no completed games yet, or the week ahead is past
    week 14 (playoffs — this feature is regular-season only).
    """
    years = {g["year"] for g in all_games}
    if not years:
        return None
    current_year = max(years)
    current_season_games = [g for g in all_games
                            if g["year"] == current_year and g["game_type"] == "Regular"]
    if not current_season_games:
        return None
    last_completed_week = max(_week_sort_key(g["week"]) for g in current_season_games)
    target_week = last_completed_week + 1  # the week AHEAD, not the one just played
    if target_week > 14:
        return None

    pool = _regular_games_at_week(all_games, target_week, current_year)
    lb = _all_time_score_margin_leaderboards(all_games)

    if target_week == 1:
        return _select_week_in_history_week1(pool, lb)
    if 2 <= target_week <= 4:
        return _select_week_in_history_weeks2_4(pool, lb)
    if target_week == 5:
        return _select_week_in_history_week5(pool, all_games)
    if 6 <= target_week <= 9:
        return _select_week_in_history_weeks6_9(pool, lb)
    if target_week == 10:
        return _select_week_in_history_week10(all_games, current_year, roster_names)
    if 11 <= target_week <= 14:
        return _select_week_in_history_weeks11_14(pool, all_games, target_week, roster_names)
    return None


def compute_playoff_probability_model(all_games, roster_names):
    """
    Historical baseline: for every completed past season (one that has
    a recorded Championship game), and for weeks 3 through 13, what
    fraction of managers with a given (wins, losses) record at that
    point went on to make the playoffs that season?

    With only a handful of completed seasons, most exact (week, W, L)
    buckets have very few historical samples — sometimes exactly one,
    which produces a meaningless 0%/100% "probability" that's really
    just a single coin flip. Buckets below MIN_HISTORICAL_SAMPLES are
    dropped from exact_buckets; a coarser win%-based fallback (pooled
    across all weeks, so far more samples per bucket) is built instead
    and used when the exact bucket isn't trustworthy.
    """
    complete_years = sorted({
        g["year"] for g in all_games if g["game_type"] == "Championship"
    })
    if not complete_years:
        return None

    exact_samples = defaultdict(list)   # (week, w, l) -> [made_playoffs, ...]
    winpct_samples = defaultdict(list)  # winpct_bucket (0.0-1.0 by 0.1) -> [...]

    for yr in complete_years:
        season_games = [g for g in all_games if g["year"] == yr and g["game_type"] == "Regular"]
        if not season_games:
            continue
        playoff_mgrs = {
            mgr for g in all_games
            if g["year"] == yr and g["game_type"] in ("Quarterfinal", "Semifinal", "Championship")
            for mgr in (g["away_manager"], g["home_manager"])
        }
        weekly = _manager_week_by_week_records(season_games, range(1, 14))
        for mgr, week_records in weekly.items():
            made_playoffs = mgr in playoff_mgrs
            for wk in range(3, 14):
                if wk not in week_records:
                    continue
                w, l = week_records[wk]
                exact_samples[(wk, w, l)].append(made_playoffs)
                decided = w + l
                if decided:
                    bucket = round((w / decided) * 10) / 10  # nearest 0.1
                    winpct_samples[bucket].append(made_playoffs)

    exact_buckets = {}
    for key, vals in exact_samples.items():
        if len(vals) >= MIN_HISTORICAL_SAMPLES:
            wk, w, l = key
            exact_buckets[f"{wk}_{w}_{l}"] = {
                "n": len(vals), "rate": round(sum(vals) / len(vals), 4),
            }

    winpct_fallback = {}
    for bucket, vals in winpct_samples.items():
        winpct_fallback[str(bucket)] = {
            "n": len(vals), "rate": round(sum(vals) / len(vals), 4),
        }

    return {
        "seasons_used": complete_years,
        "min_samples": MIN_HISTORICAL_SAMPLES,
        "exact_buckets": exact_buckets,
        "winpct_fallback": winpct_fallback,
    }


def compute_playoff_probabilities(all_games, roster_names, model):
    """
    Current-season playoff probability per active manager, using the
    historical model above as a base rate, then nudged by two
    tiebreakers among managers sharing the exact same record (tiered by
    the size of the gap, see compute_tie_adjustments):
      - More points scored so far → higher probability (up to ±5 pts)
      - Harder schedule (lower schedule_difficulty) → higher probability,
        since their record undersells their true quality (up to ±5 pts)

    After the tie-break nudges, any manager who has mathematically clinched
    a playoff spot is set to 100% and flagged "clinched": true; any manager
    mathematically eliminated is set to 0% and flagged "eliminated": true;
    everyone else is kept within 1%-99%
    (see compute_playoff_status — exact when the full remaining schedule is
    available and few enough games remain, otherwise a schedule-blind bound).

    Visibility rules (handled by the caller, not here): hidden before
    week 3, hidden once the season is fully complete (14 weeks +
    playoffs recorded).
    """
    if not model:
        return None

    years = {g["year"] for g in all_games}
    if not years:
        return None
    current_year = max(years)

    # If this season already has a Championship game, it's fully
    # decided — no probability to show.
    if any(g["year"] == current_year and g["game_type"] == "Championship" for g in all_games):
        return {"season": current_year, "visible": False, "reason": "season_complete", "managers": []}

    season_games = [g for g in all_games if g["year"] == current_year and g["game_type"] == "Regular"]
    if not season_games:
        return None

    weeks_present = {_week_sort_key(g["week"]) for g in season_games}
    current_week = max(weeks_present) if weeks_present else 0

    if current_week < 3:
        return {"season": current_year, "visible": False, "reason": "too_early", "current_week": current_week, "managers": []}
    if current_week >= 14:
        return {"season": current_year, "visible": False, "reason": "season_complete", "managers": []}

    weekly = _manager_week_by_week_records(season_games, range(1, current_week + 1))

    # Points scored and schedule difficulty so far this season, reusing
    # the same computation the Power Rankings page already needs.
    points_scored = defaultdict(float)
    games_played = defaultdict(int)
    for g in season_games:
        points_scored[g["away_manager"]] += g["away_score"]
        points_scored[g["home_manager"]] += g["home_score"]
        games_played[g["away_manager"]] += 1
        games_played[g["home_manager"]] += 1

    pr = compute_power_rankings(all_games, roster_names)
    sched_diff = {r["manager"]: r["schedule_difficulty"] for r in (pr["rankings"] if pr else [])}

    exact_buckets = model["exact_buckets"]
    winpct_fallback = model["winpct_fallback"]

    def base_rate(w, l):
        key = f"{current_week}_{w}_{l}"
        if key in exact_buckets:
            b = exact_buckets[key]
            return b["rate"], f"exact ({b['n']} historical samples)"
        decided = w + l
        if decided:
            bucket = round((w / decided) * 10) / 10
            fb = winpct_fallback.get(str(bucket))
            if fb:
                return fb["rate"], f"win% fallback ({fb['n']} historical samples)"
        return 0.5, "no historical data — neutral default"

    entries = []
    for mgr in roster_names:
        if mgr not in weekly or current_week not in weekly[mgr]:
            continue
        w, l = weekly[mgr][current_week]
        rate, basis = base_rate(w, l)
        entries.append({
            "manager": mgr, "wins": w, "losses": l,
            "base_rate": rate, "basis": basis,
            "points_scored": round(points_scored.get(mgr, 0.0), 2),
            "schedule_difficulty": sched_diff.get(mgr, 0.0),
        })

    # Adjust for ties on identical (wins, losses) using the tiered
    # head-to-head comparisons in compute_tie_adjustments() above. A group
    # of size 1 gets no adjustment (nothing to break a tie against).
    groups = defaultdict(list)
    for e in entries:
        groups[(e["wins"], e["losses"])].append(e)

    for group in groups.values():
        if len(group) < 2:
            group[0]["probability"] = round(min(100, max(0, group[0]["base_rate"] * 100)), 1)
            continue
        adjustments = compute_tie_adjustments(group)
        for e in group:
            points_adj, sched_adj = adjustments[e["manager"]]
            pct = e["base_rate"] * 100 + points_adj + sched_adj
            e["probability"] = round(min(100, max(0, pct)), 1)

    # Clinch override: a manager who can't be caught by enough rivals in the
    # games that remain is at 100% no matter what the base rate or the
    # tie-break nudges say.
    records = {e["manager"]: (e["wins"], e["losses"]) for e in entries}
    schedule = load_remaining_schedule(
        records.keys(), games_played, current_year, current_week
    )
    clinched, eliminated, status_method = compute_playoff_status(
        records, games_played, schedule
    )
    for e in entries:
        e["clinched"] = e["manager"] in clinched
        e["eliminated"] = e["manager"] in eliminated
        if e["clinched"]:
            e["probability"] = 100.0      # displayed as "Clinched"
        elif e["eliminated"]:
            e["probability"] = 0.0        # displayed as "Eliminated"
        else:
            # Still alive: never show 100% (that's reserved for a clinch) or
            # 0% (reserved for elimination), however extreme the model gets.
            e["probability"] = round(min(99.0, max(1.0, e["probability"])), 1)

    entries.sort(key=lambda e: -e["probability"])
    return {"season": current_year, "visible": True, "current_week": current_week,
            "status_method": status_method, "managers": entries}


def compute_h2h_summary(all_games, roster_names):
    """
    Per-manager all-time stats for the Head-to-Head comparison page.
    Deliberately independent of the MSI's career rollup (which only
    counts complete seasons on purpose) — this page is a live "how do
    these two compare right now" tool, not an official season-end
    accolade tracker, so it includes the in-progress season too.
    """
    manager_games = defaultdict(list)
    for g in all_games:
        manager_games[g["away_manager"]].append(g)
        manager_games[g["home_manager"]].append(g)

    out = {}
    for mgr in roster_names:
        glist = manager_games.get(mgr, [])
        seasons_played = len({g["year"] for g in glist})

        wins = losses = ties = 0
        rs_wins = rs_losses = rs_ties = 0
        po_wins = po_losses = po_ties = 0
        rs_points = 0.0
        rs_games = 0
        playoff_appearances = 0
        points_titles = 0
        championships = 0
        seasons_with_playoffs = set()
        seasons_with_titles = set()

        for g in glist:
            is_regular = g["game_type"] == "Regular"
            if g["tie"]:
                ties += 1
                if is_regular:
                    rs_ties += 1
                else:
                    po_ties += 1
            elif g["winner"] == mgr:
                wins += 1
                if is_regular:
                    rs_wins += 1
                else:
                    po_wins += 1
            else:
                losses += 1
                if is_regular:
                    rs_losses += 1
                else:
                    po_losses += 1

            if is_regular:
                score = g["away_score"] if g["away_manager"] == mgr else g["home_score"]
                rs_points += score
                rs_games += 1
            else:
                seasons_with_playoffs.add(g["year"])
                if g["game_type"] == "Championship" and g["winner"] == mgr:
                    championships += 1

        playoff_appearances = len(seasons_with_playoffs)

        # Points titles: highest cumulative regular-season points_for
        # that season, computed fresh here (same rule as recompute_stats,
        # but re-derived rather than reused since that function is
        # scoped to complete seasons only).
        season_points = defaultdict(lambda: defaultdict(float))
        for g in all_games:
            if g["game_type"] != "Regular":
                continue
            season_points[g["year"]][g["away_manager"]] += g["away_score"]
            season_points[g["year"]][g["home_manager"]] += g["home_score"]
        for year, totals in season_points.items():
            if not totals:
                continue
            top = max(totals.values())
            if totals.get(mgr) == top:
                seasons_with_titles.add(year)
        points_titles = len(seasons_with_titles)

        # Longest all-time regular-season winning streak (same rule as
        # the Record Books streak record: playoffs skipped entirely,
        # continues across season boundaries).
        reg_games = sorted(
            [g for g in glist if g["game_type"] == "Regular"],
            key=lambda g: (g["year"], _week_sort_key(g["week"])),
        )
        cur_streak = best_streak = 0
        for g in reg_games:
            if g["tie"]:
                cur_streak = 0
            elif g["winner"] == mgr:
                cur_streak += 1
                best_streak = max(best_streak, cur_streak)
            else:
                cur_streak = 0

        decided = wins + losses
        rs_decided = rs_wins + rs_losses
        po_decided = po_wins + po_losses
        out[mgr] = {
            "seasons_played": seasons_played,
            "wins": wins, "losses": losses, "ties": ties,
            "win_pct": round(wins / decided, 4) if decided else 0.0,
            "rs_wins": rs_wins, "rs_losses": rs_losses, "rs_ties": rs_ties,
            "rs_win_pct": round(rs_wins / rs_decided, 4) if rs_decided else 0.0,
            "po_wins": po_wins, "po_losses": po_losses, "po_ties": po_ties,
            "po_win_pct": round(po_wins / po_decided, 4) if po_decided else 0.0,
            "rs_avg_score": round(rs_points / rs_games, 2) if rs_games else 0.0,
            "longest_win_streak": best_streak,
            "playoff_appearances": playoff_appearances,
            "points_titles": points_titles,
            "championships": championships,
        }

    return out


def generate_25wins_banner(fastest_to_25_wins):
    """
    Overlays the current Fastest to 25 Wins leaderboard onto the blank
    banner template, replacing whatever was there before. Runs
    automatically every ingestion — no separate step to remember.

    Font size shrinks automatically as the list grows (more managers
    hit 25 wins over time), down to a floor where it stops shrinking
    and instead lets rows get tighter together — past roughly 10-12
    names this will start looking cramped and may need a redesigned
    template with more vertical room, but that's a real ceiling on
    THIS template, not something auto-shrinking text can solve forever.
    """
    if not PIL_AVAILABLE:
        print("WARNING: Pillow not installed — skipping banner generation. "
              "Run 'pip install Pillow --break-system-packages' to enable it.")
        return
    if not BANNER_BLANK_PATH.exists():
        print(f"WARNING: {BANNER_BLANK_PATH} not found — skipping banner generation.")
        return
    if not fastest_to_25_wins:
        print("No Fastest to 25 Wins data yet — skipping banner generation.")
        return

    lines = [f"{e['manager']} - {e['games']}" for e in fastest_to_25_wins]

    banner = Image.open(BANNER_BLANK_PATH).convert("RGBA")
    draw = ImageDraw.Draw(banner)

    # Empty area on this specific template: below the "25 WINS" title,
    # above the trophy graphic. Hardcoded to this template's layout —
    # a different blank banner image would need these recalibrated.
    top_bound, bottom_bound = 460, 1080
    available_height = bottom_bound - top_bound
    center_x = banner.width // 2

    # Auto-shrink: start at 62px for up to 5 lines (the size already
    # confirmed to look right), scale down as more lines are added,
    # with a floor of 28px so text never becomes illegible — beyond
    # that floor, rows just pack tighter rather than the font shrinking
    # further.
    base_size = 62
    base_line_count = 5
    font_size = min(base_size, int(base_size * base_line_count / max(len(lines), base_line_count)))
    font_size = max(font_size, 28)
    font = ImageFont.truetype(str(BANNER_FONT_PATH), font_size)

    line_spacing = available_height / len(lines)
    text_color = (245, 235, 220, 255)
    shadow_color = (0, 0, 0, 180)

    for i, line in enumerate(lines):
        y = top_bound + line_spacing * i + line_spacing / 2
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        x = center_x - w / 2
        ty = y - h / 2 - bbox[1]
        draw.text((x + 3, ty + 3), line, font=font, fill=shadow_color)
        draw.text((x, ty), line, font=font, fill=text_color)

    SITE_IMAGES_DIR = BANNER_OUTPUT_PATH.parent
    SITE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    banner.save(BANNER_OUTPUT_PATH)
    print(f"Wrote {BANNER_OUTPUT_PATH} ({len(lines)} names, {font_size}px font)")


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python ingest_csv.py path/to/weekly.csv")
    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        sys.exit(f"ERROR: {csv_path} not found.")

    roster_names = load_roster()
    stats = load_json(STATS_PATH, {"last_updated": None, "games": [], "managers": {}})

    stats["games"] = ingest_new_games(csv_path, stats["games"], roster_names)
    stats["managers"] = recompute_stats(stats["games"], roster_names)
    stats["records"] = compute_records(stats["games"], roster_names)
    generate_25wins_banner(stats["records"]["fastest_to_25_wins"])
    stats["power_rankings"] = compute_power_rankings(stats["games"], roster_names)
    stats["current_streaks"] = compute_current_streaks(stats["games"], roster_names)
    stats["current_standings"] = compute_standings(stats["games"], roster_names)
    stats["week_in_history"] = compute_week_in_history(stats["games"], roster_names)
    stats["more_you_know"] = compute_more_you_know(stats["games"], roster_names)
    if stats["more_you_know"]:
        mtk = stats["more_you_know"]
        print(f"The More You Know: {mtk['reason']} -> {mtk['value']} "
              f"(sample size {mtk.get('sample_size')})")
    else:
        print("The More You Know: nothing defined for this week yet.")
    if stats["week_in_history"]:
        wih = stats["week_in_history"]
        print(f"This Week in Club History: picked {wih['year']} Week {wih['week']} — "
              f"{wih['away_manager']} {wih['away_score']} @ {wih['home_manager']} {wih['home_score']} "
              f"— reason: {wih['selection_reason']} {wih['selection_detail']}")
    else:
        print("This Week in Club History: no eligible candidate this week.")
    stats["playoff_probability_model"] = compute_playoff_probability_model(stats["games"], roster_names)
    stats["playoff_probabilities"] = compute_playoff_probabilities(
        stats["games"], roster_names, stats["playoff_probability_model"]
    )
    complete_years = {g["year"] for g in stats["games"] if g["game_type"] == "Championship"}
    stats["msi_last_complete_season"] = max(complete_years) if complete_years else None
    stats["h2h_summary"] = compute_h2h_summary(stats["games"], roster_names)
    stats["last_updated"] = date.today().isoformat()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATS_PATH, "w") as f:
        json.dump(stats, f, indent=2)

    print(f"Done. {len(stats['games'])} total games in log. Wrote {STATS_PATH}")


if __name__ == "__main__":
    main()
