"""
Lists every trade ESPN recorded for one season: date, the two managers,
and the players each one received. Read-only: prints to the console and,
when run in GitHub Actions, writes a table to the job summary and a CSV
(path in TRADE_HISTORY_CSV) for download. Writes nothing in the repo.

ESPN only knows about players; draft-pick trades are made outside ESPN,
so they don't appear here.

Run by the "ESPN trade history" workflow:
    python scripts/trade_history.py 2024
"""

import csv
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from espn_api.football import League

from espn_pull import load_credentials, load_team_mapping

EASTERN = ZoneInfo("America/New_York")
PAGE = 25  # ESPN returns at most 25 per message type per call


def player_name(player):
    return getattr(player, "name", None) or str(player)


def season_trades(league, year, mapping):
    """[{date, managers: {manager: [players received]}}] oldest first."""
    out = []
    offset = 0
    for _ in range(40):
        batch = league.recent_activity(size=PAGE, msg_type="TRADED", offset=offset)
        for activity in batch:
            received = {}
            for team, action, player, *_ in activity.actions:
                if action != "TRADE_RECEIVED" or not team:
                    continue
                manager = mapping.get((str(year), team.team_name), team.team_name)
                received.setdefault(manager, []).append(player_name(player))
            if received:
                when = datetime.fromtimestamp(activity.date / 1000, tz=timezone.utc).astimezone(EASTERN)
                out.append({"date": when, "managers": received})
        if len(batch) < PAGE:
            break
        offset += PAGE
    return sorted(out, key=lambda t: t["date"])


def main():
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        sys.exit("Usage: python trade_history.py <season, e.g. 2024>")
    year = int(sys.argv[1])
    league_id, swid, espn_s2 = load_credentials()
    league = League(league_id=league_id, year=year, espn_s2=espn_s2, swid=swid)
    trades = season_trades(league, year, load_team_mapping())

    print(f"{len(trades)} trades on ESPN for {year}:")
    rows = []
    for i, t in enumerate(trades, 1):
        sides = " | ".join(f"{m} receives {', '.join(p)}" for m, p in t["managers"].items())
        print(f"{i:>3}. {t['date']:%Y-%m-%d}  {sides}")
        for manager, players in t["managers"].items():
            rows.append([i, t["date"].strftime("%Y-%m-%d"), manager, ", ".join(players)])

    csv_path = os.environ.get("TRADE_HISTORY_CSV")
    if csv_path:
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Trade", "Date", "Manager receives", "Players"])
            writer.writerows(rows)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(f"## ESPN trades, {year} season ({len(trades)})\n\n")
            f.write("Players only: draft-pick trades are made outside ESPN.\n\n")
            f.write("| # | Date | Manager receives | Players |\n|---|---|---|---|\n")
            for i, date, manager, players in rows:
                f.write(f"| {i} | {date} | {manager} | {players} |\n")


if __name__ == "__main__":
    main()
