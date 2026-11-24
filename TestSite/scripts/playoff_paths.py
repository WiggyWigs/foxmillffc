"""
Playoff Paths for the Current Season page: for every team still alive,
what it needs from its own remaining games and everyone else's to make
the playoffs (top 6) and, from the publication after Week 12, to finish
1st or 2nd (a bye).

Exact, not simulated: every win/loss combination of the remaining
regular-season games is played out (2^games: 18 games after Week 11 is
262,144) and ranked with the same rules as rank_season_games() in
ingest_csv.py: win %, then a tied group is sorted by pure pairwise
head-to-head among only the tied teams, and if any pair in the group is
undetermined (never played, or split) or the head-to-head win counts
don't give a strict order, the whole group goes to total points. Points
for games not yet played are unknown, so a combination where a team's
fate rests on a points tiebreaker counts as "points", neither in nor out.

For each team the combinations are grouped by its own results (which of
its remaining games it wins) and summed up in plain lines:
  - CLINCHED / ELIMINATED / only alive through a total-points tiebreaker
  - needs N of [teams] to finish below W wins: in without any tiebreaker
    if so. The list is every team that can still reach W wins and isn't
    already there; N is how many of them must fall short.
plus a key game: of its own remaining games, the one where a win instead
of a loss adds the most combinations in which it's in without a
tiebreaker (every other game counted as a coin flip).

Called by ingest_csv.py (compute_playoff_paths); writes nothing itself.
"""

from collections import Counter
from itertools import combinations

FIRST_PATHS_WEEK = 11  # playoff paths from the publication after this week
FIRST_BYE_WEEK = 12    # bye paths from the publication after this week
BYE_SPOTS = 2
MAX_GAMES = 20         # at most 2^20 combinations; more and the section is skipped
NEAR_TIE = 0.005       # key games within half a point of share are "just as big"


def first_name(m):
    """Short name for the write-ups; the two Brians keep their last names."""
    return m if m.startswith("Brian") else m.split()[0]


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def _join(names, last="&"):
    names = list(names)
    if len(names) <= 2:
        return f" {last} ".join(names)
    return ", ".join(names[:-1]) + f" {last} " + names[-1]


def enumerate_statuses(season_games, managers, games, spots):
    """statuses[m]: bytearray over every combination (bit i set = the
    first-listed team won game i): 1 in, 0 out, 2 points tiebreaker.
    Returns (statuses, wins so far)."""
    idx = {m: i for i, m in enumerate(managers)}
    n = len(managers)
    wins = [0] * n
    h2h = [[0] * n for _ in range(n)]
    for g in season_games:
        if g["tie"]:
            continue
        w, l = idx[g["winner"]], idx[g["loser"]]
        wins[w] += 1
        h2h[w][l] += 1
    total = 1 << len(games)
    statuses = [bytearray(total) for _ in range(n)]
    for c in range(total):
        w = wins[:]
        h = [row[:] for row in h2h]
        for i, (a, b) in enumerate(games):
            x, y = (a, b) if (c >> i) & 1 else (b, a)
            w[x] += 1
            h[x][y] += 1
        order = sorted(range(n), key=lambda m: -w[m])
        pos = i = 0
        while i < n and pos < spots:
            j = i
            while j + 1 < n and w[order[j + 1]] == w[order[i]]:
                j += 1
            group = order[i:j + 1]
            size = len(group)
            if pos + size <= spots:
                for m in group:
                    statuses[m][c] = 1
            else:
                undetermined = False
                beat = {m: 0 for m in group}
                for p, q in combinations(group, 2):
                    if h[p][q] > h[q][p]:
                        beat[p] += 1
                    elif h[q][p] > h[p][q]:
                        beat[q] += 1
                    else:
                        undetermined = True
                if undetermined or len(set(beat.values())) < size:
                    for m in group:
                        statuses[m][c] = 2
                else:
                    for k, m in enumerate(sorted(group, key=lambda m: -beat[m])):
                        statuses[m][c] = 1 if pos + k < spots else 0
            pos += size
            i = j + 1
    return statuses, wins


def describe(group, own):
    """Plain words for a set of own-result patterns (frozensets of the
    names of opponents beaten): "Win out", "Any 2 wins", "Beat X",
    "Beat X + 1 more win", "1 win, over X or Y", ... joined by "; or "."""
    k = len(own)
    allp = {frozenset(s) for c in range(k + 1) for s in combinations(own, c)}
    cands = []
    for c in range(k + 1):
        exact = {p for p in allp if len(p) == c}
        if c == k:
            cands.append(("Win out" if k > 1 else f"Beat {own[0]}", exact))
        elif c == 0:
            cands.append(("Lose out" if k > 1 else f"Lose to {own[0]}", exact))
        else:
            cands.append((_plural(c, "win"), exact))
            cands.append((f"Any {_plural(c, 'win')}" if c > 1 else "Any win",
                          {p for p in allp if len(p) >= c}))
            cands.append((f"{_plural(c, 'win')} or fewer", {p for p in allp if len(p) <= c}))
    for o in own:
        cands.append((f"Beat {o}", {p for p in allp if o in p}))
        for c in range(2, k):
            cands.append((f"Beat {o} + {_plural(c - 1, 'more win')}",
                          {p for p in allp if o in p and len(p) == c}))
    for r in range(2, k):
        for opps in combinations(own, r):
            cands.append((f"1 win, over {_join(opps, 'or')}", {frozenset([o]) for o in opps}))
    for p in allp:
        if 0 < len(p) < k:
            beat = [o for o in own if o in p]
            lost = [o for o in own if o not in p]
            text = (f"1 win, over {beat[0]}" if len(beat) == 1
                    else f"Beat {_join(beat)}, lose to {_join(lost)}")
            cands.append((text, {p}))
    group = set(group)
    cands = [(t, s) for t, s in cands if s <= group]
    chosen, left = [], set(group)
    while left:
        t, s = max(cands, key=lambda ts: (len(ts[1] & left), len(ts[1]), -len(ts[0])))
        chosen.append((t, s))
        left -= s
    # Most wins first ("Win out, or beat X + 1 more win"), later pieces
    # lower-cased so they read as one sentence.
    chosen.sort(key=lambda ts: (-max(len(p) for p in ts[1]), -len(ts[1])))
    texts = [t for t, _ in chosen]
    return ", or ".join([texts[0]] + [t[0].lower() + t[1:] for t in texts[1:]])


def team_paths(m, managers, statuses, wins, losses, games, game_weeks, spots):
    """Write-up for one team (index m), or None if every combination has
    it out."""
    st = statuses[m]
    if not any(st):
        return None
    total = len(st)
    own = [i for i, (a, b) in enumerate(games) if m in (a, b)]
    opp = [games[i][1] if games[i][0] == m else games[i][0] for i in own]
    names = [first_name(managers[o]) for o in opp]
    left = Counter()
    for a, b in games:
        left[a] += 1
        left[b] += 1
    final_games = wins[m] + losses[m] + len(own)

    def won(c, j):
        i = own[j]
        return ((c >> i) & 1) == (1 if games[i][0] == m else 0)

    by_pattern = {}
    for c in range(total):
        p = frozenset(names[j] for j in range(len(own)) if won(c, j))
        by_pattern.setdefault(p, []).append(c)

    keyed = {}
    for p, cs in by_pattern.items():
        counts = Counter(st[c] for c in cs)
        W = wins[m] + len(p)
        if counts[1] == len(cs):
            key = ("clinch",)
        elif counts[0] == len(cs):
            key = ("elim",)
        elif counts[1] == 0:
            key = ("points",)
        else:
            beaten = {opp[j] for j in range(len(own)) if names[j] in p}
            already = [o for o in range(len(managers)) if o != m and wins[o] >= W]
            can = [o for o in range(len(managers))
                   if o != m and wins[o] < W and wins[o] + left[o] - (o in beaten) >= W]
            can.sort(key=lambda o: (W - wins[o], o))
            need = max(0, len(can) - (spots - 1 - len(already)))
            key = ("need", W, need, tuple(first_name(managers[o]) for o in can), counts[0] > 0)
        keyed.setdefault(key, []).append(p)

    rank = {"clinch": 0, "need": 1, "points": 2, "elim": 3}
    lines = []
    for key, group in keyed.items():
        when = describe(group, names)
        Ws = {wins[m] + len(p) for p in group}
        if len(Ws) == 1:
            W = Ws.pop()
            when += f" ({W}-{final_games - W})"
        kind = key[0]
        if kind == "clinch":
            text = "CLINCHED."
        elif kind == "elim":
            text = "ELIMINATED."
        elif kind == "points":
            text = "only alive through a total-points tiebreaker."
        else:
            _, W, need, lst, can_be_out = key
            tail = " Otherwise it comes down to tiebreakers" + (" (or they're out)." if can_be_out else ".")
            text = ("in." if need == 0 else
                    f"needs {need} of {', '.join(lst)} to finish below {W} wins.") + tail
        lines.append((rank[kind], -max(len(p) for p in group), when, text, kind))
    lines.sort()

    half = total // 2
    swings = []
    for j in range(len(own)):
        w_in = sum(1 for c in range(total) if st[c] == 1 and won(c, j))
        l_in = sum(1 for c in range(total) if st[c] == 1 and not won(c, j))
        swings.append((round((w_in - l_in) / half, 6), -j, w_in / half, l_in / half))
    swings.sort(reverse=True)
    key_game = None
    if swings and swings[0][0] > 0:
        sw, nj, w_pct, l_pct = swings[0]
        j = -nj
        key_game = {
            "week": game_weeks[own[j]], "opponent": names[j],
            "win_in": round(w_pct, 4), "lose_in": round(l_pct, 4),
            "also": [f"Wk {game_weeks[own[-x[1]]]} vs {names[-x[1]]}"
                     for x in swings[1:] if sw - x[0] <= NEAR_TIE],
        }

    counts = Counter(st)
    status = ("clinched" if counts[1] == total else
              "points_only" if counts[1] == 0 else "alive")
    return {
        "manager": managers[m],
        "rank": m + 1,
        "record": f"{wins[m]}-{losses[m]}",
        "remaining": [{"week": game_weeks[own[j]], "opponent": names[j]} for j in range(len(own))],
        "status": status,
        "in_share": round(counts[1] / total, 4),
        "lines": [{"when": w, "text": t, "kind": k} for _, _, w, t, k in lines],
        "key_game": key_game,
    }


def build(season_games, standings, remaining, remaining_weeks, spots):
    """[write-up] for every team still alive for the top `spots`, in
    standings order (standings: rows from rank_season_games). remaining:
    list of weeks, each a list of (manager, manager) pairs; remaining_weeks:
    the week numbers of those weeks. None if too many games are left."""
    managers = [row["manager"] for row in standings]
    idx = {m: i for i, m in enumerate(managers)}
    games, game_weeks = [], []
    for wk, week in zip(remaining_weeks, remaining):
        for a, b in week:
            games.append((idx[a], idx[b]))
            game_weeks.append(wk)
    if not games or len(games) > MAX_GAMES:
        return None
    statuses, wins = enumerate_statuses(season_games, managers, games, spots)
    losses = [row["losses"] for row in standings]
    out = []
    for m in range(len(managers)):
        tp = team_paths(m, managers, statuses, wins, losses, games, game_weeks, spots)
        if tp:
            out.append(tp)
    return out
