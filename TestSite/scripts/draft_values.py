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
     player's position, floored at 0. Replacement = the median season of
     non-keeper players at that position drafted in REPLACEMENT_ROUNDS
     (the kind of player that's still there late or on waivers); with
     fewer than 3 of those, the position's 20th percentile instead.
  3. Per round: the median value over replacement (robust to a few
     breakout seasons).
  4. A smooth curve, value = e^(a - k*(round - 1)), fitted to the rounds
     with a median above 0 (least squares on the log, weighted by each
     round's median so near-zero late rounds don't swing it), scaled so
     Round 1 = 100. Shown next to the current 15-down-to-1 scale.

Run by the "Draft pick values" workflow:
    python scripts/draft_values.py 2023,2024,2025
"""

import csv
import math
import os
import statistics
import sys

from espn_api.football import League

from espn_pull import load_credentials, load_team_mapping

REPLACEMENT_ROUNDS = (13, 14, 15)
CARD_BATCH = 50


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


def drafted_players(year, league_id, swid, espn_s2, mapping):
    league = League(league_id=league_id, year=year, espn_s2=espn_s2, swid=swid)
    if not league.draft:
        print(f"{year}: no draft on ESPN, skipped.")
        return []
    points = season_points(league, {p.playerId for p in league.draft if p.playerId})
    rows = []
    for p in league.draft:
        pts, pos = points.get(p.playerId, (None, "?"))
        rows.append({
            "year": year, "round": p.round_num, "pick": p.round_pick,
            "manager": mapping.get((str(year), getattr(p.team, "team_name", None)), getattr(p.team, "team_name", "?")),
            "player": p.playerName, "position": pos, "points": pts,
            "keeper": bool(p.keeper_status),
        })
    missing = sum(1 for r in rows if r["points"] is None)
    print(f"{year}: {len(rows)} picks, {sum(r['keeper'] for r in rows)} keepers"
          + (f", {missing} without season points" if missing else ""))
    return rows


def replacement_levels(rows):
    """{position: replacement points} from non-keepers drafted late."""
    by_pos = {}
    for r in rows:
        if not r["keeper"] and r["points"] is not None:
            by_pos.setdefault(r["position"], []).append(r)
    levels = {}
    for pos, group in by_pos.items():
        late = [r["points"] for r in group if r["round"] in REPLACEMENT_ROUNDS]
        if len(late) >= 3:
            levels[pos] = statistics.median(late)
        else:
            pts = sorted(r["points"] for r in group)
            levels[pos] = pts[int(0.2 * (len(pts) - 1))]
    return levels


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
    rows = [r for y in years for r in drafted_players(y, league_id, swid, espn_s2, mapping)]

    levels = replacement_levels(rows)
    for r in rows:
        r["over_replacement"] = (max(0.0, r["points"] - levels.get(r["position"], 0.0))
                                 if r["points"] is not None else None)

    rounds = sorted({r["round"] for r in rows})
    used = {rd: [r for r in rows if r["round"] == rd and not r["keeper"] and r["points"] is not None]
            for rd in rounds}
    med_pts = {rd: statistics.median([r["points"] for r in g]) if g else 0 for rd, g in used.items()}
    med_vor = {rd: statistics.median([r["over_replacement"] for r in g]) if g else 0 for rd, g in used.items()}
    fit = fit_curve(med_vor)
    if fit:
        a, k = fit
        curve = {rd: math.exp(a - k * (rd - 1)) for rd in rounds}
        top = curve[rounds[0]]
        scaled = {rd: 100 * v / top for rd, v in curve.items()}
    else:
        k, scaled = None, {rd: 0 for rd in rounds}

    lines = [
        f"## Draft pick values, {', '.join(map(str, years))}",
        "",
        f"Keepers left out. Replacement level by position (median of picks in rounds "
        f"{REPLACEMENT_ROUNDS[0]}-{REPLACEMENT_ROUNDS[-1]}): "
        + ", ".join(f"{pos} {v:.1f}" for pos, v in sorted(levels.items())),
        "",
        (f"Fitted curve: each round is worth {100 * math.exp(-k):.0f}% of the one before it."
         if k is not None else "Not enough data to fit a curve."),
        "",
        "| Round | Players | Median points | Median over replacement | Curve (Rd 1 = 100) | Curve (Rd 1 = 15) | Current scale |",
        "|---|---|---|---|---|---|---|",
    ]
    for rd in rounds:
        lines.append(f"| {rd} | {len(used[rd])} | {med_pts[rd]:.1f} | {med_vor[rd]:.1f} | "
                     f"{scaled[rd]:.1f} | {scaled[rd] * 0.15:.2f} | {max(0, 16 - rd)} |")
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
