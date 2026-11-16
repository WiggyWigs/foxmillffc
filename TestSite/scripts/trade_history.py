"""
Lists every trade ESPN recorded for one season: date, the managers, and
the players each one received. Read-only: prints to the console and,
when run in GitHub Actions, writes a table to the job summary and a CSV
(path in TRADE_HISTORY_CSV) for download. Writes nothing in the repo.

Two sources, tried in order:
  1. The league activity feed (what the site already reads for the
     current season's trade counts).
  2. If the feed has no trades for the season, ESPN's weekly
     transactions list: every scoring period is checked for accepted
     trades (TRADE_ACCEPT), with player lists filled in from player
     cards when ESPN leaves them out for other teams' trades.
The log says how many activity items ESPN returned at all, so an empty
result can be told apart from a season ESPN won't serve.

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


def to_eastern(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(EASTERN)


def from_activity_feed(league, manager_of):
    """Trades from the activity feed: [{date, managers: {manager: [players]}}].
    ESPN doesn't always say which team received a player; in a two-team
    trade it's the other team, so that's filled in."""
    out, offset, seen = [], 0, 0
    for _ in range(40):
        batch = league.recent_activity(size=PAGE, msg_type="TRADED", offset=offset)
        seen += len(batch)
        for activity in batch:
            teams = {t.team_id: t for t, *_ in activity.actions if t}
            received = {}
            for team, action, player, *_ in activity.actions:
                if not team:
                    continue
                if action == "TRADE_RECEIVED":
                    getter = team
                elif action == "TRADE_SENT" and len(teams) == 2 and not any(
                        a == "TRADE_RECEIVED" for _, a, *_ in activity.actions):
                    getter = next(t for tid, t in teams.items() if tid != team.team_id)
                else:
                    continue
                received.setdefault(manager_of(getter), []).append(player_name(player))
            if received:
                out.append({"date": to_eastern(activity.date), "managers": received})
        if len(batch) < PAGE:
            break
        offset += PAGE
    print(f"Activity feed: {seen} trade activities returned.")
    return out


def from_weekly_transactions(league, manager_of):
    """Trades from the weekly transactions list (TRADE_ACCEPT), every
    scoring period of the season."""
    out, ids = [], set()
    last_week = getattr(league, "finalScoringPeriod", None) or 18
    for week in range(0, last_week + 1):
        try:
            txns = league.transactions(scoring_period=week, types={"TRADE_ACCEPT"},
                                       fill_trade_items=True)
        except Exception as e:
            if "No transactions" not in str(e):
                print(f"Week {week}: couldn't read transactions ({e})")
            continue
        for t in txns:
            if t.type != "TRADE_ACCEPT" or t.id in ids:
                continue
            ids.add(t.id)
            received = {}
            for item in t.items:
                getter = league.get_team_data(item.to_team_id) if item.to_team_id else None
                if getter:
                    received.setdefault(manager_of(getter), []).append(player_name(item.player))
            if not received:
                received[manager_of(t.team) if t.team else f"Team {t.team_id}"] = ["(players not listed by ESPN)"]
            out.append({"date": to_eastern(t.date) if t.date else None, "managers": received,
                        "week": t.scoring_period})
    print(f"Weekly transactions: {len(out)} accepted trades found across weeks 0-{last_week}.")
    return out


def main():
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        sys.exit("Usage: python trade_history.py <season, e.g. 2024>")
    year = int(sys.argv[1])
    league_id, swid, espn_s2 = load_credentials()
    league = League(league_id=league_id, year=year, espn_s2=espn_s2, swid=swid)
    mapping = load_team_mapping()

    def manager_of(team):
        return mapping.get((str(year), team.team_name), team.team_name)

    try:
        any_activity = len(league.recent_activity(size=PAGE))
    except Exception as e:
        any_activity = f"error: {e}"
    print(f"Activity feed for {year}: {any_activity} items of any kind on the first page.")

    trades, source = from_activity_feed(league, manager_of), "activity feed"
    if not trades:
        trades, source = from_weekly_transactions(league, manager_of), "weekly transactions"
    trades.sort(key=lambda t: (t["date"] is None, t["date"] or datetime.min.replace(tzinfo=EASTERN)))

    print(f"\n{len(trades)} trades on ESPN for {year} (from the {source}):")
    rows = []
    for i, t in enumerate(trades, 1):
        date = t["date"].strftime("%Y-%m-%d") if t["date"] else f"week {t.get('week', '?')}"
        sides = " | ".join(f"{m} receives {', '.join(p)}" for m, p in t["managers"].items())
        print(f"{i:>3}. {date}  {sides}")
        for manager, players in t["managers"].items():
            rows.append([i, date, manager, ", ".join(players)])

    csv_path = os.environ.get("TRADE_HISTORY_CSV")
    if csv_path:
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Trade", "Date", "Manager receives", "Players"])
            writer.writerows(rows)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(f"## ESPN trades, {year} season ({len(trades)}, from the {source})\n\n")
            f.write("Players only: draft-pick trades are made outside ESPN.\n\n")
            f.write("| # | Date | Manager receives | Players |\n|---|---|---|---|\n")
            for i, date, manager, players in rows:
                f.write(f"| {i} | {date} | {manager} | {players} |\n")


if __name__ == "__main__":
    main()
