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
STATS_PATH = DATA_DIR / os.environ.get("STATS_FILENAME", "stats.json")
STATS_SNAPSHOT_PATH = DATA_DIR / os.environ.get("STATS_SNAPSHOT_FILENAME", "stats_previous_run.json")
UPCOMING_MATCHUPS_PATH = DATA_DIR / os.environ.get("UPCOMING_MATCHUPS_FILENAME", "upcoming_matchups.json")
PLAYER_LINEUPS_PATH = DATA_DIR / os.environ.get("PLAYER_LINEUPS_FILENAME", "player_lineups.json")
RECAP_CRITERIA_PATH = SCRIPT_DIR / "recap_criteria.json"
MANAGER_LORE_PATH = SCRIPT_DIR / "manager_lore.json"
NARRATIVE_TONE_PATH = SCRIPT_DIR / "narrative_tone.txt"

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


def load_manager_lore():
    """Edit manager_lore.json directly to add or change material —
    no code changes needed."""
    if not MANAGER_LORE_PATH.exists():
        return {}
    with open(MANAGER_LORE_PATH) as f:
        return json.load(f)


def load_narrative_tone():
    """Edit narrative_tone.txt directly to change the voice/tone both
    narratives are written in — no code changes needed. Falls back to
    a plain, safe default if the file is ever missing, rather than
    failing the whole run over a style file."""
    if not NARRATIVE_TONE_PATH.exists():
        return "Write in a clear, engaging tone appropriate for a fantasy football league website."
    return NARRATIVE_TONE_PATH.read_text().strip()


def get_manager_flavor(manager, stats, lore):
    """Real, verified career facts for one manager — actual roast
    material, not invented. Pulled from h2h_summary (the same all-time
    stats the Head-to-Head page uses), plus any lore.json entry."""
    flavor = {}
    h2h = stats.get("h2h_summary", {}).get(manager)
    if h2h:
        flavor["seasons_played"] = h2h.get("seasons_played")
        flavor["career_playoff_appearances"] = h2h.get("playoff_appearances")
        flavor["career_championships"] = h2h.get("championships")
        flavor["career_win_pct"] = h2h.get("win_pct")
    note = lore.get(manager)
    if note:
        flavor["background_note"] = note
    return flavor


def get_playoff_probability_trend(manager, old_stats, new_stats):
    """This manager's playoff probability last week vs. this week —
    the ONLY acceptable way to reference playoff chances in a
    narrative (never a vague qualitative claim). Returns None unless
    the "previous" snapshot is verifiably from an earlier week than
    the current one — without this check, two test runs that aren't
    genuinely sequential (e.g. the same cutoff week run twice) would
    silently report a manager's probability as "unchanged" just
    because it's literally the same computation compared to itself,
    not a real week-over-week trend."""
    old_pp = (old_stats or {}).get("playoff_probabilities")
    new_pp = (new_stats or {}).get("playoff_probabilities")
    if not old_pp or not new_pp or not old_pp.get("visible") or not new_pp.get("visible"):
        return None

    old_season, old_week = old_pp.get("season"), old_pp.get("current_week")
    new_season, new_week = new_pp.get("season"), new_pp.get("current_week")
    if old_season is None or new_season is None or old_week is None or new_week is None:
        return None
    if (old_season, old_week) >= (new_season, new_week):
        # Not genuinely "previous" — same week, or somehow later.
        # Reporting a trend here would be actively misleading.
        return None

    def lookup(pp):
        for row in pp.get("managers", []):
            if row["manager"] == manager:
                return row["probability"]
        return None

    previous = lookup(old_pp)
    current = lookup(new_pp)
    if previous is None and current is None:
        return None
    return {"previous_week_pct": previous, "current_week_pct": current}


# --- Claude API ---------------------------------------------------------

def call_claude(system_prompt, user_prompt, max_tokens=2000):
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
    text = "".join(block["text"] for block in data["content"] if block["type"] == "text").strip()

    if not text:
        # This happened silently before — no exception, but nothing
        # usable either. Surface the actual API response so the real
        # cause (stop_reason, content filtering, etc.) is visible in
        # the Action log instead of just quietly saving an empty string.
        stop_reason = data.get("stop_reason")
        raise RuntimeError(
            f"Claude returned no usable text (stop_reason={stop_reason!r}). "
            f"Full response: {json.dumps(data)[:500]}"
        )
    return text


# --- Shared helpers -------------------------------------------------------

def week_num(w):
    return int(w) if str(w).isdigit() else 0


def h2h_record(manager_a, manager_b, all_games):
    """Real head-to-head win-loss record between two managers, all
    games all-time (not just a meeting count)."""
    a_wins = b_wins = ties = 0
    for g in all_games:
        if {g["away_manager"], g["home_manager"]} != {manager_a, manager_b}:
            continue
        if g["tie"]:
            ties += 1
        elif g["winner"] == manager_a:
            a_wins += 1
        else:
            b_wins += 1
    return a_wins, b_wins, ties


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
        away_wins, home_wins, h2h_ties = h2h_record(away, home, stats["games"])
        enriched.append({
            "away_manager": away, "away_team": g["away_team"], "away_score": g["away_score"],
            "home_manager": home, "home_team": g["home_team"], "home_score": g["home_score"],
            "margin": round(g["score_diff"], 2),
            "all_time_meetings": len(h2h_games),
            "h2h_record": f"{away} leads {away_wins}-{home_wins}" if away_wins > home_wins
                else f"{home} leads {home_wins}-{away_wins}" if home_wins > away_wins
                else f"series tied {away_wins}-{home_wins}",
        })
    return enriched, latest_week, current_year


# --- Previous Weekend Recap (AI writes about a fixed, deterministic pick) --

def get_manager_lineup(year, week, manager):
    """This manager's full lineup (starters + bench) for a specific
    week, or None if not captured."""
    if not PLAYER_LINEUPS_PATH.exists():
        return None
    with open(PLAYER_LINEUPS_PATH) as f:
        lineups = json.load(f)
    for entry in lineups:
        if entry["year"] == str(year) and week_num(entry["week"]) == week_num(week) and entry["manager"] == manager:
            return entry["players"]
    return None


def top_and_bottom_starter(lineup):
    """(highest-scoring starter, lowest-scoring starter) from a lineup,
    or (None, None) if there are no starters recorded."""
    starters = [p for p in lineup if p.get("started")]
    if not starters:
        return None, None
    top = max(starters, key=lambda p: p["points"])
    bottom = min(starters, key=lambda p: p["points"])
    return top, bottom


def find_best_bench_swap(losing_lineup, points_needed):
    """
    Checks every (bench player, starter) pair for LEGAL eligibility
    (the bench player's real eligible_slots from ESPN must include the
    starter's actual slot — this is not guessed or hardcoded, it's the
    league's own real position rules, including whatever counts as
    FLEX-eligible here). Among all legal swaps, returns the single
    best one by point gain, and whether that gain alone would have
    closed the gap. Only ever considers ONE swap, not combinations —
    a "what if" story needs one clear swap, not a hypothetical full
    lineup optimization.
    """
    starters = [p for p in losing_lineup if p.get("started")]
    bench = [p for p in losing_lineup if not p.get("started")]
    if not starters or not bench:
        return None

    best = None
    for b in bench:
        eligible = b.get("eligible_slots", [])
        for s in starters:
            if s["slot"] not in eligible:
                continue  # not a legal swap under this league's real rules
            gain = b["points"] - s["points"]
            if best is None or gain > best["gain"]:
                best = {
                    "bench_player": b["name"], "bench_points": b["points"],
                    "starter_replaced": s["name"], "starter_points": s["points"],
                    "gain": round(gain, 2),
                }

    if best is None:
        return None
    best["would_have_won"] = best["gain"] >= points_needed
    return best


def build_recap_prompt(closest_game, week, year, stats, lore, old_stats, tone):
    away, home = closest_game["away_manager"], closest_game["home_manager"]
    away_score, home_score = closest_game["away_score"], closest_game["home_score"]

    context = dict(closest_game)  # copy — don't mutate the caller's dict
    away_team, home_team = context.pop("away_team", None), context.pop("home_team", None)

    # Player-level context, if lineup data was captured for this week.
    # This is genuinely optional: if player_lineups.json doesn't have
    # this week yet, the recap still works fine without it.
    # Thresholds are hard rules, not prompt suggestions: a "big score"
    # under 15 isn't actually impressive, and a "pathetic score" over
    # 10 isn't actually bad — so those just don't get mentioned at all.
    HIGH_SCORE_THRESHOLD = 15
    LOW_SCORE_THRESHOLD = 10

    away_lineup = get_manager_lineup(year, week, away)
    home_lineup = get_manager_lineup(year, week, home)

    if away_lineup:
        top, bottom = top_and_bottom_starter(away_lineup)
        if top and top["points"] > HIGH_SCORE_THRESHOLD:
            context["away_top_scorer"] = {"name": top["name"], "points": top["points"]}
        if bottom and bottom["points"] < LOW_SCORE_THRESHOLD:
            context["away_bottom_scorer"] = {"name": bottom["name"], "points": bottom["points"]}
    if home_lineup:
        top, bottom = top_and_bottom_starter(home_lineup)
        if top and top["points"] > HIGH_SCORE_THRESHOLD:
            context["home_top_scorer"] = {"name": top["name"], "points": top["points"]}
        if bottom and bottom["points"] < LOW_SCORE_THRESHOLD:
            context["home_bottom_scorer"] = {"name": bottom["name"], "points": bottom["points"]}

    # Bench-swap analysis for the losing team only (a winning team has
    # no "what if" story — they already won).
    loser = None
    if away_score != home_score:
        loser = away if away_score < home_score else home
        losing_lineup = away_lineup if away_score < home_score else home_lineup
        margin = abs(away_score - home_score)
        if losing_lineup:
            swap = find_best_bench_swap(losing_lineup, margin)
            if swap and swap["would_have_won"]:
                context["bench_swap_that_would_have_won"] = swap

    # Real, verified career context — this is the actual roast material.
    away_flavor = get_manager_flavor(away, stats, lore)
    home_flavor = get_manager_flavor(home, stats, lore)
    if away_flavor:
        context["away_manager_background"] = away_flavor
    if home_flavor:
        context["home_manager_background"] = home_flavor

    # Playoff probability trend — the ONLY acceptable way to mention
    # playoff chances (never a vague qualitative claim).
    away_pp = get_playoff_probability_trend(away, old_stats, stats)
    home_pp = get_playoff_probability_trend(home, old_stats, stats)
    if away_pp:
        context["away_season_playoff_probability_trend"] = away_pp
    if home_pp:
        context["home_season_playoff_probability_trend"] = home_pp

    system = (
        "You write short fantasy football recap blurbs for a private "
        "league's website — a group of 40-something guys who have known "
        "each other for years and enjoy busting each other's chops.\n\n"
        f"{tone}\n\n"
        "The recap must be between 95 "
        "and 125 words — this is a hard requirement, not a suggestion. "
        "Use ONLY the facts given — never invent player names, stats, "
        "plays, or background details beyond what's provided. Do not use "
        "markdown formatting. Do NOT start with the manager names or a "
        "'ManagerA vs ManagerB:' prefix — that's shown separately on the "
        "page. Just start straight into the recap itself. EVERY field "
        "given is prefixed with either 'season_' or 'career_' to show "
        "its scope — whenever you state ANY number from a season_ or "
        "career_ field, you MUST include a matching word in the "
        "sentence itself ('this season', 'career', 'all-time', etc.) "
        "so a reader always knows which scope it's from — never state "
        "a number without that context. Whenever you "
        "state a player's point total, always write it as 'X points' or "
        "'X.X points' — never a bare number on its own. Whenever you "
        "state a percentage (playoff probability or anything else), "
        "always write it as 'X%' or 'X.X%' — never spell out 'percent' "
        "as a word. Win percentages (career_win_pct or any other "
        "win_pct field) are given as decimals (e.g. 0.6818) — always "
        "convert to a whole-number percentage with two decimals and "
        "spell out the words, e.g. 'a 68.18 winning percentage' — never "
        "write the raw decimal or abbreviate to 'win pct'. Mention AT MOST "
        "one standout performance and ONE disappointing performance per "
        "team, and ONLY the specific players named in the top/bottom "
        "scorer fields given — never reference, name, or invent stats "
        "for any other player not explicitly provided. Frame any "
        "top/bottom scorer mention as a dramatic contrast in one "
        "sentence — the big performance overcoming, carrying, or "
        "outshining the weak one (or vice versa) — never as two flat, "
        "separate statements listing each player's score. Vary the "
        "verb and the adjective each time rather than reusing the same "
        "phrasing. If you mention "
        "playoff chances or probability for a manager, you MUST cite "
        "both their previous_week_pct and current_week_pct numbers from "
        "their season_playoff_probability_trend field if it's present — never "
        "make a vague qualitative claim about playoff odds without "
        "those two real numbers. If that field isn't present for a "
        "manager, don't speculate about their playoff chances at all."
    )
    user = (
        f"Write a recap of the closest game of Week {week}, {year} — this "
        f"was the tightest matchup of the week by score margin:\n"
        f"{json.dumps(context, indent=2)}\n\n"
        f"Mention the final score and margin. If all_time_meetings is "
        f"more than 1, you can briefly note this isn't their first "
        f"meeting, using the h2h_record field for the real all-time "
        f"record between them (e.g. 'X leads Y-Z') — don't invent "
        f"details about those past games beyond what's given. If "
        f"top/bottom scorer fields are present, you can mention a "
        f"standout or disappointing individual performance if it fits "
        f"naturally, following the one-per-team limit above. If "
        f"bench_swap_that_would_have_won is present, that's a real, "
        f"verified fact — a bench player who would have won the game if "
        f"started instead of the named starter — and it's usually prime "
        f"material for mocking whoever set that lineup. If "
        f"away_manager_background or home_manager_background is present "
        f"(especially for {loser or 'the loser'}, who lost this game), "
        f"use it as real ammunition — a bad career record, zero playoff "
        f"appearances, a background_note personality trait, etc. are all "
        f"fair game and encouraged, not just optional color."
    )
    return system, user, away_team, home_team


# --- Game of the Week (AI both picks and writes) ---------------------------

def build_game_of_week_prompt(upcoming, stats, criteria, lore, old_stats, tone):
    matchups = upcoming.get("matchups", [])
    if not matchups:
        return None, None

    standings = {}
    standings_rank = {}
    if stats.get("current_standings"):
        for i, row in enumerate(stats["current_standings"]["standings"]):
            standings[row["manager"]] = row
            standings_rank[row["manager"]] = i + 1  # already sorted with the real H2H/points tiebreak logic

    power = {}
    if stats.get("power_rankings"):
        for row in stats["power_rankings"]["rankings"]:
            power[row["manager"]] = row

    playoff_prob = {}
    pp = stats.get("playoff_probabilities")
    if pp and pp.get("visible"):
        for row in pp["managers"]:
            playoff_prob[row["manager"]] = row["probability"]

    def manager_context(name):
        p = power.get(name, {})
        wins = standings.get(name, {}).get("wins")
        losses = standings.get(name, {}).get("losses")
        games_played = (wins or 0) + (losses or 0)
        points_total = p.get("points_scored")
        points_avg = round(points_total / games_played, 2) if points_total is not None and games_played else None
        ctx = {
            "season_standings_rank": standings_rank.get(name),
            "season_wins": wins,
            "season_losses": losses,
            "season_power_score": p.get("power_score"),
            "season_points_avg": points_avg,
            "season_schedule_difficulty": p.get("schedule_difficulty"),
            "season_playoff_probability_pct": playoff_prob.get(name),
        }
        flavor = get_manager_flavor(name, stats, lore)
        if flavor:
            ctx["background"] = flavor
        pp_trend = get_playoff_probability_trend(name, old_stats, stats)
        if pp_trend:
            ctx["season_playoff_probability_trend"] = pp_trend
        return ctx

    enriched = []
    for m in matchups:
        away, home = m["away_manager"], m["home_manager"]
        away_wins, home_wins, h2h_ties = h2h_record(away, home, stats["games"])
        h2h_meetings = away_wins + home_wins + h2h_ties
        enriched.append({
            "away_manager": away, "away_team": m.get("away_team"),
            **{f"away_{k}": v for k, v in manager_context(away).items()},
            "home_manager": home, "home_team": m.get("home_team"),
            **{f"home_{k}": v for k, v in manager_context(home).items()},
            "all_time_meetings": h2h_meetings,
            "h2h_record": f"{away} leads {away_wins}-{home_wins}" if away_wins > home_wins
                else f"{home} leads {home_wins}-{away_wins}" if home_wins > away_wins
                else f"series tied {away_wins}-{home_wins}",
        })

    system = (
        "You pick the single most compelling upcoming matchup from a list "
        "for a private fantasy football league's website — a group of "
        "40-something guys who have known each other for years and enjoy "
        "busting each other's chops — based on the selection criteria "
        "given, then write a short preview of it. You MUST pick one of "
        "the matchups and write about it, every single time — even if "
        "none of them perfectly satisfy the criteria. If nothing clearly "
        "fits, use your best judgment to pick the closest available "
        "match to what the criteria is asking for and proceed normally; "
        "never respond with nothing, an apology, or a refusal to choose. "
        f"{tone}\n\n"
        "The preview must be between "
        "95 and 125 words for the preview itself, not counting the "
        "required prefix below — this is a hard requirement, not a "
        "suggestion. Use ONLY the facts given — never invent player "
        "names, projections, stats, or background details not provided. "
        "Do not use markdown formatting. EVERY field given is prefixed "
        "with either 'season_' or 'career_' to show its scope — whenever "
        "you state ANY number from a season_ or career_ field, you MUST "
        "include a matching word in the sentence itself ('this season', "
        "'career', 'all-time', etc.) so a reader always knows which "
        "scope it's from — never state a number without that context, "
        "especially when a season stat and a career stat appear near "
        "each other in the same sentence. Whenever you state a point "
        "total, always write it as 'X points' or 'X.X points' — never a "
        "bare number alone. Points totals given are SEASON AVERAGES "
        "(season_points_avg) — always describe them as such (e.g. "
        "'averaging X points a game this season'), never imply it's a "
        "season total or a career figure. "
        "Whenever you state a percentage (playoff "
        "probability or anything else), always write it as 'X%' or "
        "'X.X%' — never spell out 'percent' as a word. Win percentages "
        "(career_win_pct or any other win_pct field) are given as "
        "decimals (e.g. 0.6818) — always convert to a whole-number "
        "percentage with two decimals and spell out the words, e.g. "
        "'a 68.18 career winning percentage' — never write the raw "
        "decimal or abbreviate to 'win pct'. When referring "
        "to a manager's standings position, always phrase it as an "
        "ordinal — 'ranked 2nd this season', 'sits 5th in the "
        "standings', etc. — "
        "never 'rank 2' or 'at rank 5' as a bare number. IMPORTANT: "
        "season_schedule_difficulty is counterintuitively named — a HIGHER "
        "(more positive) value means an EASIER schedule, and a LOWER "
        "(more negative, or less positive) value means a HARDER "
        "schedule. The value itself is a percentage-point gap: it's how "
        "much higher or lower a manager's actual win percentage is "
        "compared to what their weekly scoring alone would predict — "
        "describe it in those terms (e.g. 'his actual win rate runs X "
        "points ahead of what his scoring alone would suggest') rather "
        "than citing the bare decimal, which means nothing to a reader. "
        "NEVER describe one manager's schedule as easier or harder than "
        "another's unless their season_schedule_difficulty values differ by at "
        "least 0.15 — if the gap is smaller than that, it's not a real "
        "difference and shouldn't be mentioned as one at all. Whenever "
        "the selection "
        "criteria refers to a "
        "manager's 'rank' or being 'ranked' (e.g. 'top 5', 'ranked "
        "7-10'), this means their season_standings_rank field specifically — "
        "their position in the actual win-loss standings — NOT their "
        "season_power_score or any other number. If you use the all-time "
        "meetings history, "
        "use the h2h_record field for the real record (e.g. 'X leads "
        "Y-Z') — don't invent details beyond what's given. If you "
        "mention playoff chances or probability for a manager, you MUST "
        "cite both their previous_week_pct and current_week_pct numbers "
        "from their season_playoff_probability_trend field if present — never a "
        "vague qualitative claim without those two real numbers; if "
        "that field isn't present for a manager, don't speculate about "
        "their playoff chances. If you reference a manager's individual "
        "top or bottom player performance, frame it as a dramatic "
        "contrast in one sentence — the big performance overcoming, "
        "carrying, or outshining the weak one (or vice versa) — never "
        "as two flat, separate statements listing each player's score. "
        "Vary the verb and the adjective each time rather than reusing "
        "the same phrasing. You MUST start your response with the "
        "two manager names in the exact format 'ManagerA vs ManagerB: ' "
        "(this prefix is required for internal tracking and will be "
        "removed before anyone sees it, so it does not count toward the "
        "word limit or read as part of the preview)."
    )
    user = (
        f"Selection criteria: {criteria}\n\n"
        f"This week's matchups:\n{json.dumps(enriched, indent=2)}"
    )
    return system, user


def parse_and_strip_gotw_prefix(gotw_text, upcoming):
    """The AI is required to prefix its response with 'ManagerA vs
    ManagerB: ' so we can reliably track which matchup it picked (for
    next week's result lookup) — but that prefix is redundant on the
    page itself, since the team-name subtitle already shows this.
    Returns (matchup_info_or_None, display_text_with_prefix_removed).
    Falls back to the original text unchanged if parsing fails, rather
    than losing the narrative over a formatting slip."""
    if not gotw_text or ":" not in gotw_text or " vs " not in gotw_text.split(":", 1)[0]:
        return None, gotw_text
    try:
        header, rest = gotw_text.split(":", 1)
        a, b = [s.strip() for s in header.split(" vs ")]
        valid_managers = {m["away_manager"] for m in upcoming["matchups"]} | \
                          {m["home_manager"] for m in upcoming["matchups"]}
        if a in valid_managers and b in valid_managers:
            matchup_info = {"manager_a": a, "manager_b": b,
                             "week": upcoming.get("week"), "year": upcoming.get("year")}
            return matchup_info, rest.strip()
    except Exception:
        pass
    return None, gotw_text


# --- Callout: last week's featured Game of the Week, actual result --------

def callout_last_gotw_result(old_stats, new_games):
    """This one stays sentence-style rather than the name+number card
    format — a head-to-head result genuinely doesn't compress into a
    single headline and number the way the others do."""
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
    return {
        "style": "sentence",
        "label": "LAST WEEK'S PICK",
        "text": (f"{a} vs {b} went to {winner}, "
                 f"{match['away_manager']} {match['away_score']} - "
                 f"{match['home_score']} {match['home_manager']}."),
    }


# --- Callout: new record set this week -------------------------------------

RECORD_LIST_LABELS = {
    "top_avg_regular_season": "Top Average Score",
    "bottom_avg_regular_season": "Lowest Average Score",
    "top_regular_season_games": "Highest R/S Game Score",
    "bottom_regular_season_games": "Lowest R/S Game Score",
    "top_playoff_games": "Highest Playoff Score",
    "bottom_playoff_games": "Lowest Playoff Score",
    "top_winning_streaks": "Longest Win Streak (All-Time)",
    "top_losing_streaks": "Longest Losing Streak (All-Time)",
    "top_over100_streaks": "Longest Streak Over 100",
    "top_under100_streaks": "Longest Streak Under 100",
    "fastest_to_25_wins": "Fastest to 25 Wins",
    "fastest_to_50_wins": "Fastest to 50 Wins",
    "fastest_to_25_losses": "Fastest to 25 Losses",
    "fastest_to_50_losses": "Fastest to 50 Losses",
}


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
            callouts.append({
                "style": "card",
                "label": "NEW RECORD",
                "headline": names,
                "subtitle": RECORD_LIST_LABELS.get(key, key.replace("_", " ")),
                "value": new_top_value,
                "unit": "",
            })

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
        win_callout = {
            "style": "card", "label": "WIN STREAK", "headline": names,
            "subtitle": "active streak", "value": streak, "unit": "games",
        }
    if cs.get("top_current_losing_streaks"):
        top = cs["top_current_losing_streaks"]
        streak = top[0]["loss_streak"]
        names = ", ".join(e["manager"] for e in top if e["loss_streak"] == streak)
        loss_callout = {
            "style": "card", "label": "LOSING STREAK", "headline": names,
            "subtitle": "active streak", "value": streak, "unit": "games",
        }
    return win_callout, loss_callout


def callout_biggest_margin(week_games):
    if not week_games:
        return None
    biggest = max(week_games, key=lambda g: g["margin"])
    winner = biggest["away_manager"] if biggest["away_score"] > biggest["home_score"] else biggest["home_manager"]
    loser = biggest["home_manager"] if winner == biggest["away_manager"] else biggest["away_manager"]
    return {
        "style": "card", "label": "BLOWOUT", "headline": winner,
        "subtitle": f"over {loser}", "value": biggest["margin"], "unit": "points",
    }


def callout_lowest_scoring_team(week_games):
    if not week_games:
        return None
    all_scores = []
    for g in week_games:
        all_scores.append((g["away_manager"], g["away_score"]))
        all_scores.append((g["home_manager"], g["home_score"]))
    manager, score = min(all_scores, key=lambda t: t[1])
    return {
        "style": "card", "label": "ICE COLD", "headline": manager,
        "subtitle": "lowest score this week", "value": score, "unit": "points",
    }


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
    return {
        "style": "card", "label": "STANDOUT", "headline": best["player"],
        "subtitle": f"{best['manager']} \u00b7 {best['position']}",
        "value": best["points"], "unit": "points",
    }


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
    lore = load_manager_lore()
    tone = load_narrative_tone()
    week_games, week, year = get_week_games(stats)

    recap_text = None
    recap_away_team = recap_home_team = None
    gotw_text = None
    gotw_matchup = None
    gotw_away_team = gotw_home_team = None

    # --- Previous Weekend Recap: always the closest game ---
    try:
        if week_games:
            closest_game = min(week_games, key=lambda g: g["margin"])
            system, user, recap_away_team, recap_home_team = build_recap_prompt(
                closest_game, week, year, stats, lore, old_stats, tone
            )
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
            system, user = build_game_of_week_prompt(upcoming, stats, week_criteria, lore, old_stats, tone)
            if system:
                raw_gotw_text = call_claude(system, user)
                gotw_matchup, gotw_text = parse_and_strip_gotw_prefix(raw_gotw_text, upcoming)
                if gotw_matchup:
                    picked = next(
                        (m for m in upcoming["matchups"]
                         if {m["away_manager"], m["home_manager"]} == {gotw_matchup["manager_a"], gotw_matchup["manager_b"]}),
                        None,
                    )
                    if picked:
                        gotw_away_team, gotw_home_team = picked.get("away_team"), picked.get("home_team")
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
        "previous_weekend_week": week if week_games else None,
        "previous_weekend_away_team": recap_away_team,
        "previous_weekend_home_team": recap_home_team,
        "game_of_the_week": gotw_text,
        "game_of_the_week_week": upcoming.get("week") if upcoming else None,
        "game_of_the_week_matchup": gotw_matchup,  # structured, for next week's result lookup
        "game_of_the_week_away_team": gotw_away_team,
        "game_of_the_week_home_team": gotw_home_team,
        "callouts": callouts,
    }
    with open(STATS_PATH, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"Saved recap content to {STATS_PATH}.")


if __name__ == "__main__":
    main()
