"""
Read-only backtest: would the playoff-odds simulation be more accurate if
each team's expected score reflected its current roster (trades, waiver
pickups) instead of only its season scoring average?

Pulls every regular-season box score (full rosters, starters and bench,
with each player's points) for past seasons from ESPN, keeps them in
memory, and replays each season from Week 3 to Week 13 with three ways of
setting a team's expected weekly score in the simulation:

  current   its season scoring average, pulled toward the league average
            (what the site uses now: ingest_csv.simulate_playoff_odds)
  recent    the same, but recent weeks count more (RECENT_DECAY per week)
  roster    a projection from its latest roster: each player's average
            this season (on any team, bye weeks and 0-point weeks left
            out), the best lineup those averages allow, scaled so the
            league's projections average the league's real scoring, then
            blended with "current" (ROSTER_SHARES)

Two scores, both lower = better:
  1. Next-week error: how far each method's expected score was from the
     team's real score the following week (average absolute miss). Many
     data points (teams x weeks x seasons), so it's the sharper test.
  2. Playoff odds Brier score (finished seasons only): the full odds the site would have shown
     (history blend, clinch and the 1-99% cap as in production), scored
     against who made the playoffs. Each season's history model is built
     only from the other seasons.
Every method is scored on the same team-weeks: a week without every
team's roster is left out for all of them.

Writes nothing in the repo: prints to the log and, in GitHub Actions,
to the run's summary page. Run by the "Lineup projection backtest"
workflow:
    python scripts/lineup_backtest.py 2023,2024,2025
"""

import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from espn_api.football import League

import ingest_csv as ic
from espn_pull import load_credentials, load_team_mapping

SCRIPT_DIR = Path(__file__).parent
STATS_PATH = SCRIPT_DIR.parent / "data" / "stats.json"

SIM_RUNS = 2000          # per week per method (the site uses 10,000)
RECENT_DECAY = 0.85      # "recent": each week counts 85% of the one after it
ROSTER_SHARES = (0.5, 1.0)  # "roster": share of the projection in the blend
OUT_SLOTS = {"BE", "IR"}


def fetch_lineups(year, league_id, swid, espn_s2, mapping, weeks):
    """{week: {manager: [player dicts]}} from ESPN's box scores. Logs how
    many lineups each week returned, so a season ESPN won't serve shows."""
    try:
        league = League(league_id=league_id, year=year, espn_s2=espn_s2, swid=swid)
    except Exception as e:
        print(f"{year}: couldn't load the league ({e!r})")
        return {}
    out, cache = {}, {}
    for week in weeks:
        try:
            boxes = league.box_scores(week=week, player_team_cache=cache)
        except Exception as e:
            print(f"{year} Week {week}: couldn't fetch box scores ({e!r})")
            continue
        week_out, unmapped = {}, set()
        for bs in boxes:
            for team, lineup in ((bs.away_team, bs.away_lineup), (bs.home_team, bs.home_lineup)):
                if not team or not lineup:
                    continue
                manager = mapping.get((str(year), team.team_name))
                if not manager:
                    unmapped.add(team.team_name)
                    continue
                week_out[manager] = [{
                    "id": p.playerId, "name": p.name, "position": p.position,
                    "slot": p.slot_position, "points": p.points or 0.0,
                    "bye": bool(getattr(p, "on_bye_week", False)),
                    "eligible": list(getattr(p, "eligibleSlots", []) or []),
                } for p in lineup]
        if unmapped:
            print(f"{year} Week {week}: no manager for team(s) {sorted(unmapped)}")
        out[week] = week_out
        print(f"{year} Week {week}: {len(week_out)} lineups, "
              f"{sum(len(v) for v in week_out.values())} players")
        time.sleep(0.3)
    return out


def starting_slots(lineups):
    """The league's usual starting slots, e.g. {'QB':1,'RB':2,...}, from
    the most common set of started slots across every team-week."""
    shapes = Counter()
    for week in lineups.values():
        for players in week.values():
            shape = Counter(p["slot"] for p in players if p["slot"] not in OUT_SLOTS)
            shapes[tuple(sorted(shape.items()))] += 1
    return dict(shapes.most_common(1)[0][0]) if shapes else {}


def player_averages(lineups, through_week):
    """{player id: average points} over weeks <= through_week in which the
    player was on any roster, wasn't on bye and scored something."""
    pts = defaultdict(list)
    for week, teams in lineups.items():
        if week > through_week:
            continue
        for players in teams.values():
            for p in players:
                if not p["bye"] and p["points"] != 0:
                    pts[p["id"]].append(p["points"])
    return {pid: sum(v) / len(v) for pid, v in pts.items()}


def best_lineup_points(players, averages, slots):
    """Sum of averages for the best lineup the roster allows: the slots
    with the fewest eligible players are filled first, each with the best
    remaining eligible player."""
    pool = [p for p in players if p["slot"] != "IR" and p["id"] in averages]
    open_slots = [s for s, n in slots.items() for _ in range(n)]
    open_slots.sort(key=lambda s: sum(s in p["eligible"] for p in pool))
    used, total = set(), 0.0
    for slot in open_slots:
        options = [p for p in pool if p["id"] not in used and slot in p["eligible"]]
        if options:
            best = max(options, key=lambda p: averages[p["id"]])
            used.add(best["id"])
            total += averages[best["id"]]
    return total


def expected_scores(season_games, week, lineups, slots, method, share=1.0):
    """{manager: expected weekly score} from games through `week`."""
    pts = defaultdict(list)
    for g in season_games:
        if ic._week_sort_key(g["week"]) <= week:
            pts[g["away_manager"]].append((ic._week_sort_key(g["week"]), g["away_score"]))
            pts[g["home_manager"]].append((ic._week_sort_key(g["week"]), g["home_score"]))
    every = [s for v in pts.values() for _, s in v]
    league_avg = sum(every) / len(every)
    prior = ic.SIM_PRIOR_GAMES

    def shrunk(weights):
        out = {}
        for m, v in pts.items():
            wsum = sum(weights(wk) for wk, _ in v)
            out[m] = (sum(weights(wk) * s for wk, s in v) + prior * league_avg) / (wsum + prior)
        return out

    base = shrunk(lambda wk: 1.0)
    if method == "current":
        return base
    if method == "recent":
        return shrunk(lambda wk: RECENT_DECAY ** (week - wk))
    # roster
    if week not in lineups or not lineups[week]:
        return None
    averages = player_averages(lineups, week)
    proj = {m: best_lineup_points(lineups[week][m], averages, slots)
            for m in base if m in lineups[week]}
    if len(proj) != len(base) or not any(proj.values()):
        return None
    scale = league_avg / (sum(proj.values()) / len(proj))
    return {m: share * proj[m] * scale + (1 - share) * base[m] for m in base}


def simulate(season_games, roster, remaining, expected, spread, seed):
    """Share of SIM_RUNS seasons each manager finishes in the top
    PLAYOFF_SPOTS, ranked by the real standings rules."""
    rng = random.Random(seed)
    made = defaultdict(int)
    for _ in range(SIM_RUNS):
        games = list(season_games)
        for week in remaining:
            for a, b in week:
                sa, sb = rng.gauss(expected[a], spread), rng.gauss(expected[b], spread)
                games.append({"away_manager": a, "home_manager": b, "away_score": sa,
                              "home_score": sb, "away_team": "", "home_team": "",
                              "tie": sa == sb, "winner": a if sa > sb else b,
                              "loser": b if sa > sb else a})
        for row in ic.rank_season_games(games, roster)[:ic.PLAYOFF_SPOTS]:
            made[row["manager"]] += 1
    return {m: made[m] / SIM_RUNS for m in roster}


def main():
    years = [int(y) for y in (sys.argv[1] if len(sys.argv) > 1 else "2023,2024,2025").split(",")]
    league_id, swid, espn_s2 = load_credentials()
    mapping = load_team_mapping()
    all_games = json.load(open(STATS_PATH))["games"]
    wk = ic._week_sort_key

    methods = [("current", "current", 1.0), ("recent", "recent", 1.0)] + [
        (f"roster {int(s * 100)}%", "roster", s) for s in ROSTER_SHARES]
    errors = defaultdict(list)            # method -> [abs miss]
    brier = defaultdict(lambda: defaultdict(list))  # method -> band -> [(p, made)]
    coverage = {}

    for year in years:
        season = [g for g in all_games if g["year"] == year and g["game_type"] == "Regular"]
        if not season:
            print(f"{year}: no regular-season games in stats.json, skipped")
            continue
        last = max(wk(g["week"]) for g in season)
        roster = sorted({m for g in season for m in (g["away_manager"], g["home_manager"])})
        made = {m for g in all_games if g["year"] == year
                and g["game_type"] in ("Quarterfinal", "Semifinal", "Championship")
                for m in (g["away_manager"], g["home_manager"])}
        finished = any(g["year"] == year and g["game_type"] == "Championship" for g in all_games)
        lineups = fetch_lineups(year, league_id, swid, espn_s2, mapping, range(1, last + 1))
        weeks_ok = sum(1 for w in lineups.values() if len(w) == len(roster))
        coverage[year] = f"{weeks_ok} of {last} weeks with every team's lineup"
        print(f"{year}: {coverage[year]}")
        slots = starting_slots(lineups)
        print(f"{year}: starting slots {slots}")
        model = ic.compute_playoff_probability_model([g for g in all_games if g["year"] != year], roster)

        for w in range(3, 14):
            if w >= last:
                break
            trunc = [g for g in season if wk(g["week"]) <= w]
            next_scores = {}
            for g in season:
                if wk(g["week"]) == w + 1:
                    next_scores[g["away_manager"]] = g["away_score"]
                    next_scores[g["home_manager"]] = g["home_score"]
            remaining = [[(g["away_manager"], g["home_manager"]) for g in season if wk(g["week"]) == x]
                         for x in range(w + 1, last + 1)]
            hist = ic.compute_playoff_probabilities(trunc, roster, model, schedule=None)
            if not hist or not hist.get("visible"):
                continue
            spread = ic._weekly_score_spread(trunc)
            sw = ic.sim_weight(w)
            band = "Wk 3-6" if w <= 6 else "Wk 7-10" if w <= 10 else "Wk 11-13"
            # Every method is scored on the same weeks: a week without a full
            # set of rosters is skipped for all of them.
            exps = {label: expected_scores(season, w, lineups, slots, method, share)
                    for label, method, share in methods}
            if any(v is None for v in exps.values()):
                print(f"{year} Week {w}: no full set of rosters, skipped")
                continue
            for label, method, share in methods:
                exp = exps[label]
                for m, actual in next_scores.items():
                    if m in exp:
                        errors[label].append(abs(exp[m] - actual))
                if not finished:
                    continue  # no playoff results to score the odds against
                sim = simulate(trunc, roster, remaining, exp, spread, seed=year * 100 + w)
                for e in hist["managers"]:
                    if e["clinched"]:
                        p = 100.0
                    elif e["eliminated"]:
                        p = 0.0
                    else:
                        p = min(99.0, max(1.0, sw * sim.get(e["manager"], 0) * 100 + (1 - sw) * e["probability"]))
                    for b in (band, "All"):
                        brier[label][b].append((p / 100, 1 if e["manager"] in made else 0))
            print(f"{year} Week {w}: done")

    bands = ["Wk 3-6", "Wk 7-10", "Wk 11-13", "All"]
    lines = ["| Method | Next-week miss (pts) | " + " | ".join(f"Brier {b}" for b in bands) + " |",
             "|---|---|" + "---|" * len(bands)]
    for label, _, _ in methods:
        miss = errors.get(label)
        cells = [f"{sum(miss) / len(miss):.2f} ({len(miss)})" if miss else "n/a"]
        for b in bands:
            v = brier[label].get(b)
            cells.append(f"{sum((p - y) ** 2 for p, y in v) / len(v):.4f}" if v else "n/a")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    table = "\n".join(lines)
    print("\n" + table)
    for y, c in coverage.items():
        print(f"Coverage {y}: {c}")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("## Lineup projection backtest\n\n")
            f.write("Lower is better in every column. Next-week miss = average gap between a "
                    "method's expected score and the team's real score the next week (sample size "
                    "in brackets). Brier = accuracy of the full playoff odds against who made it.\n\n")
            f.write("ESPN coverage: " + "; ".join(f"{y}: {c}" for y, c in coverage.items()) + "\n\n")
            f.write(table + "\n")


if __name__ == "__main__":
    main()
