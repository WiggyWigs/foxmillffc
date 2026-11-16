"""
How much is a pick in each draft round worth? Read-only analysis for the
Draft Capital Score: prints a per-round table to the console and, in
GitHub Actions, to the job summary, plus a CSV of every drafted player
(path in DRAFT_VALUES_CSV). Writes nothing in the repo.

Method, for every finished season given (default 2023-2025):
  1. Every drafted player's season fantasy points (ESPN, league scoring).
     Keepers are left out: a keeper is chosen in advance and kept at a
     cheap round, so its points would make that round look better than
     a normal pick there.
  2. Value over replacement: points minus a replacement level for the
     player's position in that season, floored at 0. Replacement is the
     "last starter" baseline: the league's lineup slots (from ESPN's
     settings) times the number of teams says how many players start at
     each position; flex slots go, one at a time, to the best remaining
     eligible player. Replacement is the next player after the last
     starter, ranked across the whole player pool (undrafted included),
     i.e. the best player you could have had for free. If ESPN won't
     serve the pool, drafted players only are used (logged).
  3. Per round: the median and the average value over replacement, and
     the hit rate (share of picks that beat replacement). The average is
     what a pick is worth in expectation: most late picks miss, but the
     occasional hit counts, which the median ignores.
  4. A smooth curve, value = e^(a - k*(round - 1)), fitted to the
     per-round averages (least squares on the log, weighted by each
     round's value so near-zero rounds don't swing it), scaled so
     Round 1 = 100, next to the current 15-down-to-1 scale.
  5. Trade value: only picks from FIRST_TRADEABLE_ROUND on can be traded,
     so a second curve is fitted to those rounds alone, scaled so that
     round = 100, with how many of each round equal one of it.

Run by the "Draft pick values" workflow:
    python scripts/draft_values.py 2023,2024,2025
"""

import csv
import json
import math
import os
import statistics
import sys

from espn_api.football import League

from espn_pull import load_credentials, load_team_mapping

CARD_BATCH = 50
FIRST_TRADEABLE_ROUND = 4  # league rule: only picks in Round 4 and later can be traded
POOL_SIZE = 600  # top scorers fetched per season for the replacement baseline
POSITIONS = ("QB", "RB", "WR", "TE", "K", "D/ST")
SLOT_NAMES = {0: "QB", 1: "QB", 2: "RB", 3: "RB/WR", 4: "WR", 5: "WR/TE", 6: "TE",
              7: "OP", 16: "D/ST", 17: "K", 23: "RB/WR/TE"}
FLEX = {"RB/WR": {"RB", "WR"}, "WR/TE": {"WR", "TE"},
        "RB/WR/TE": {"RB", "WR", "TE"}, "OP": {"QB", "RB", "WR", "TE"}}


def season_points(league, ids):
    """{playerId: (season fantasy points, position)} from player cards."""
    out = {}
    ids = sorted(ids)
    for i in range(0, len(ids), CARD_BATCH):
        players = league.player_info(playerId=ids[i:i + CARD_BATCH]) or []
        if not isinstance(players, list):
            players = [players]
        for p in players:
            out[p.playerId] = (float(p.total_points or 0), p.position or "?")
    return out


def player_pool_ids(league, year):
    """IDs of the season's top POOL_SIZE scorers, drafted or not (ESPN's
    player list sorted by season points). [] if ESPN won't serve it."""
    filters = {"players": {
        "filterStatus": {"value": ["FREEAGENT", "WAIVERS", "ONTEAM"]},
        "limit": POOL_SIZE,
        "sortAppliedStatTotal": {"sortAsc": False, "sortPriority": 1, "value": f"00{year}"},
    }}
    try:
        data = league.espn_request.league_get(
            params={"view": "kona_player_info", "scoringPeriodId": 0},
            headers={"x-fantasy-filter": json.dumps(filters)})
        return [p["id"] for p in data.get("players") or [] if p.get("id")]
    except Exception as e:
        print(f"{year}: couldn't read the player pool ({e!r})")
        return []


def lineup_slots(league):
    """{slot name: count per team} from ESPN's roster settings."""
    counts = league.espn_request.get_league()["settings"]["rosterSettings"]["lineupSlotCounts"]
    return {SLOT_NAMES[int(k)]: v for k, v in counts.items() if int(k) in SLOT_NAMES and v}


def replacement_levels(points_by_pos, slots, teams):
    """{position: points of the next player after the last starter} and
    {position: number of starters}.
    Direct slots first, then each flex slot to the best remaining eligible
    player, one at a time (most restrictive flex first)."""
    ranked = {pos: sorted(pts, reverse=True) for pos, pts in points_by_pos.items()}
    taken = {pos: min(slots.get(pos, 0) * teams, len(ranked.get(pos, []))) for pos in POSITIONS}
    for flex in sorted((f for f in slots if f in FLEX), key=lambda f: len(FLEX[f])):
        for _ in range(slots[flex] * teams):
            options = [pos for pos in FLEX[flex] if taken[pos] < len(ranked.get(pos, []))]
            if not options:
                break
            best = max(options, key=lambda pos: ranked[pos][taken[pos]])
            taken[best] += 1
    # The next player after the last starter. If there's nobody left (drafted
    # players only, where e.g. all 12 drafted kickers start), the median
    # player at the position: kickers and defenses get streamed, so a
    # typical one is the fair stand-in for what's free, not the worst.
    levels = {}
    for pos in POSITIONS:
        pts = ranked.get(pos, [])
        if taken[pos] < len(pts):
            levels[pos] = pts[taken[pos]]
        else:
            levels[pos] = statistics.median(pts) if pts else 0.0
    return levels, taken


def drafted_players(year, league_id, swid, espn_s2, mapping):
    league = League(league_id=league_id, year=year, espn_s2=espn_s2, swid=swid)
    if not league.draft:
        print(f"{year}: no draft on ESPN, skipped.")
        return [], None
    drafted_ids = {p.playerId for p in league.draft if p.playerId}
    pool_ids = set(player_pool_ids(league, year))
    points = season_points(league, drafted_ids | pool_ids)

    rows = []
    for p in league.draft:
        pts, pos = points.get(p.playerId, (None, "?"))
        rows.append({
            "year": year, "round": p.round_num, "pick": p.round_pick,
            "manager": mapping.get((str(year), getattr(p.team, "team_name", None)), getattr(p.team, "team_name", "?")),
            "player": p.playerName, "position": pos, "points": pts,
            "keeper": bool(p.keeper_status),
        })

    source = "whole player pool" if len(pool_ids - drafted_ids) >= 50 else "drafted players only"
    by_pos = {}
    for pid, (pts, pos) in points.items():
        if pos in POSITIONS and (source == "whole player pool" or pid in drafted_ids):
            by_pos.setdefault(pos, []).append(pts)
    slots = lineup_slots(league)
    levels, starters = replacement_levels(by_pos, slots, len(league.teams))
    for r in rows:
        r["over_replacement"] = (max(0.0, r["points"] - levels.get(r["position"], 0.0))
                                 if r["points"] is not None else None)
    missing = sum(1 for r in rows if r["points"] is None)
    print(f"{year}: {len(rows)} picks, {sum(r['keeper'] for r in rows)} keepers"
          + (f", {missing} without season points" if missing else "")
          + f"; lineup {slots}; replacement from the {source}")
    return rows, {"levels": levels, "starters": starters, "source": source}


def fit_curve(medians):
    """(a, k) for value = e^(a - k*(round - 1)): least squares on the log of
    the rounds whose median is above 0, each weighted by its median, so a
    few points of noise in a near-zero late round can't swing the slope."""
    pts = [(rd - 1, math.log(v), v) for rd, v in medians.items() if v > 0]
    if len(pts) < 2:
        return None
    w = sum(wt for *_, wt in pts)
    mx = sum(x * wt for x, _, wt in pts) / w
    my = sum(y * wt for _, y, wt in pts) / w
    slope = (sum(wt * (x - mx) * (y - my) for x, y, wt in pts)
             / sum(wt * (x - mx) ** 2 for x, _, wt in pts))
    return my - slope * mx, -slope


def main():
    years = [int(y) for y in (sys.argv[1] if len(sys.argv) > 1 else "2023,2024,2025").split(",") if y.strip()]
    league_id, swid, espn_s2 = load_credentials()
    mapping = load_team_mapping()
    rows, baselines = [], {}
    for y in years:
        season_rows, base = drafted_players(y, league_id, swid, espn_s2, mapping)
        rows += season_rows
        if base:
            baselines[y] = base

    rounds = sorted({r["round"] for r in rows})
    used = {rd: [r for r in rows if r["round"] == rd and not r["keeper"] and r["points"] is not None]
            for rd in rounds}
    med_pts = {rd: statistics.median([r["points"] for r in g]) if g else 0 for rd, g in used.items()}
    med_vor = {rd: statistics.median([r["over_replacement"] for r in g]) if g else 0 for rd, g in used.items()}
    avg_vor = {rd: statistics.mean([r["over_replacement"] for r in g]) if g else 0 for rd, g in used.items()}
    hit = {rd: (100 * sum(r["over_replacement"] > 0 for r in g) / len(g)) if g else 0 for rd, g in used.items()}

    def scaled_curve(values, base_round):
        """Curve fitted to `values`, scaled so base_round = 100; (scale, k)."""
        fit = fit_curve(values)
        if not fit:
            return {rd: 0.0 for rd in rounds}, None
        a, k = fit
        curve = {rd: math.exp(a - k * (rd - 1)) for rd in rounds}
        return {rd: 100 * v / curve[base_round] for rd, v in curve.items()}, k

    overall, k_all = scaled_curve(avg_vor, rounds[0])
    t0 = FIRST_TRADEABLE_ROUND
    tradeable = [rd for rd in rounds if rd >= t0]
    trade, k_trade = (scaled_curve({rd: avg_vor[rd] for rd in tradeable}, t0)
                      if t0 in rounds else ({}, None))

    def per_round(k):
        return f"each round is worth {100 * math.exp(-k):.0f}% of the one before it" if k is not None else "not enough data"

    lines = [
        f"## Draft pick values, {', '.join(map(str, years))}",
        "",
        "Keepers left out. Replacement = the next player after the last starter at each "
        "position (starters = lineup slots x teams, flex to the best remaining):",
        "",
        "| Season | Source | " + " | ".join(POSITIONS) + " |",
        "|---|---|" + "---|" * len(POSITIONS),
    ] + [
        f"| {y} | {b['source']} | " + " | ".join(
            f"{b['levels'][pos]:.1f} ({b['starters'][pos]} start)" for pos in POSITIONS) + " |"
        for y, b in sorted(baselines.items())
    ] + [
        "",
        "### All rounds",
        "",
        f"Curve fitted to the average over replacement: {per_round(k_all)}.",
        "",
        "| Round | Players | Median points | Median over repl. | Average over repl. | Hit rate | Curve (Rd 1 = 100) | Curve (Rd 1 = 15) | Current scale |",
        "|---|---|---|---|---|---|---|---|---|",
    ] + [
        f"| {rd} | {len(used[rd])} | {med_pts[rd]:.1f} | {med_vor[rd]:.1f} | {avg_vor[rd]:.1f} | "
        f"{hit[rd]:.0f}% | {overall[rd]:.1f} | {overall[rd] * 0.15:.2f} | {max(0, 16 - rd)} |"
        for rd in rounds
    ] + [
        "",
        f"### Trade value, Rounds {t0}-{rounds[-1]} (the tradeable picks)",
        "",
        f"Curve fitted to Rounds {t0}-{rounds[-1]} only: {per_round(k_trade)}.",
        "",
        f"| Round | Average over repl. | Hit rate | Trade value (Rd {t0} = 100) | One Rd {t0} = this many |",
        "|---|---|---|---|---|",
    ] + [
        f"| {rd} | {avg_vor[rd]:.1f} | {hit[rd]:.0f}% | {trade.get(rd, 0):.1f} | "
        f"{(100 / trade[rd]) if trade.get(rd) else 0:.1f} |"
        for rd in tradeable
    ]
    print("\n".join(lines))

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("\n".join(lines) + "\n")
    csv_path = os.environ.get("DRAFT_VALUES_CSV")
    if csv_path:
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Year", "Round", "Pick", "Manager", "Player", "Position", "Points",
                        "Over replacement", "Keeper"])
            for r in sorted(rows, key=lambda r: (r["year"], r["round"], r["pick"])):
                w.writerow([r["year"], r["round"], r["pick"], r["manager"], r["player"], r["position"],
                            "" if r["points"] is None else f"{r['points']:.1f}",
                            "" if r["over_replacement"] is None else f"{r['over_replacement']:.1f}",
                            "yes" if r["keeper"] else ""])


if __name__ == "__main__":
    main()
