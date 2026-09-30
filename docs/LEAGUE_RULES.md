# FMFFC League Rules

The rules every stats computation and write-up on this site must follow. Read this before changing anything in `scripts/`, the page JS, or `recap_criteria.json`.

If the code and this file disagree, stop and ask Greg. Do not change either one to match the other on your own.

## 1. Data handling

* All career stats come from the raw game log only. Never hand-edit `stats.json`. It is always regenerated from the full game log.
* A mid-season correction means a full rebuild from the complete, corrected CSV, not an incremental patch.
* The manager's name is the key for everything. `manager_roster.json` validates names, but an unknown name is a warning, not a failure (ESPN handles typos upstream).
* Never edit anything under `*/data/` by hand. Data files are written only by the workflows.

## 2. CSV format

* Columns: `Year, Week, Away Team, Home Team, Away Score, Home Score, Away Manager, Home Manager`
* Weeks `1`–`14` are the regular season.
* `P1` = Quarterfinal, `P2` = Semifinal, `P3` = Championship.

## 3. Manager Score Index (MSI)

```
MSI = 2.0 × (playoff appearances / seasons)
    + 1.5 × (regular-season win %)
    + 1.3 × (championships / seasons)
    + 1.0 × (points titles / seasons)
    + 0.8 × (playoff win %)
    + 0.5 × (runner-ups / seasons)

```

* Average Joe Line: 2.383

## 4. Win percentage

* Win % = wins ÷ (wins + losses + ties).
* A tie is not a win and not half a win. It counts as a game played with no win, so it lowers win %.
* This applies everywhere win % appears: standings, career stats, MSI, head-to-head, power rankings, schedule difficulty and the playoff-probability model.

## 5. Standings

* Sorted by win %.
* Tiebreak 1: head-to-head, using pure pairwise comparison among only the tied managers.
* Tiebreak 2: if any pair is unresolved or win counts still tie, use total points scored for the whole tied group. Never use the group's aggregate win %.

## 6. Streaks

* Streaks carry across season boundaries.
* Playoff games are skipped entirely. They neither extend nor break a streak.
* Only managers active in the current season are shown in current-streak displays.

## 7. Power rankings

* Schedule difficulty = actual win % minus breakdown win %.
* A lower value means a harder schedule. The lowest value (hardest schedule) earns the most power-ranking points.
* Within each category (win %, points scored, schedule difficulty), tied managers share the average of the positions they occupy. Example: two managers tied for 2nd in win % each get the points for position 2.5.
* Final displayed rank (after all category points are added up): competition-style. Tied totals share a rank and the next manager skips ahead (1, 1, 3).

## 8. Record Books leaderboards

* Ranks are competition-style: tied values share the rank of the first row with that value (1, 1, 3), matching `tieAwareRanks()` in `records.js`.
* The "Welcome to the Record Books" write-ups must use the same ranks as the Record Books page. When a mark ties one from an earlier season, the sentence says "tied for".

## 9. Playoff Probability

* Shown starting after Week 3.
* For managers with identical records, bonus points are computed from total points (not per-game averages):
   * Points gap over 15 / 30 / 45 / 60 / 75 earns +1% / 2% / 3% / 4% / 5% (max 5%).
   * Schedule-difficulty gap over 4 / 7 / 10 / 13 / 16 points earns +1% / 2% / 3% / 4% / 5% (max 5%).
* A manager who has mathematically clinched shows Clinched (bold, treated as 100%), even if a rival has more points or a harder schedule.
* A manager who is mathematically eliminated shows Eliminated (treated as 0%).
* Everyone else is capped at 99%. Never show 100% unless clinched.
* Clinching and elimination are determined from the full remaining ESPN schedule, not just current records.

## 10. Weekly recap content

### Impact Game (Previous Weekend Recap)

* Always the smallest-margin game of the most recently completed regular-season week.
* Picked by code. Claude only writes the recap.

### Honorable Mention

Picked by code, never the same game as the Impact Game:

1. Among games where both managers are top 6 in the standings, the closest margin.
2. Otherwise, the next-closest game, if its margin is under 15 points.
3. Otherwise, the week's biggest blowout, with the write-up focused on any team that scored 150+ or under 100.

### Game of the Week

* The selection rules for each week live in `scripts/recap_criteria.json`. Edit that file to change them.
* Claude picks the matchup from those rules. A separate call writes the preview.

### Rules for all write-ups

* Use only the facts provided. Never invent players, stats or history.
* Every number states its scope in the sentence ("this season", "career", "all-time").
* Point totals are written as "X points". Percentages are written as "X%". Win percentages become "a 68.2 winning percentage", never a raw decimal.
* Playoff odds may only be mentioned by citing both last week's and this week's numbers. Otherwise don't mention them.
* Don't describe one manager's schedule as easier or harder than another's unless their schedule-difficulty values differ by at least 0.15.
* Don't mention a scoring average until a manager has played at least 2 games, or schedule difficulty until at least 3 games.
* Career playoff and championship counts are only used for roasting once a manager has at least 3 complete seasons.

## Known code fixes needed

Greg has decided these rules. The code must be changed to match them.

1. Win % with ties (section 4): only career stats (`regular_win_pct` / `playoff_win_pct` around line 261 of `ingest_csv.py`) include ties in the denominator. These exclude them and must be fixed:
   * standings, `compute_standings()` (around line 905)
   * actual and breakdown win % used for schedule difficulty (around line 699)
   * playoff-probability model buckets (around lines 1921 and 2017)
   * `h2h_summary` win %, rs_win_pct and po_win_pct (around line 2178)
   * the comment around line 849 that says ties are excluded "everywhere else on this site"

   League history has one tie (2023 Week 9, Brian Kleinhenz vs John Schauder), so the fix changes 2023 numbers and those two managers' career head-to-head figures. It does not change any 2026 numbers. After the fix, regenerate `stats.json` from the full game log and show Greg a before/after of every value that changed.
2. Power-ranking ties (section 7): confirm the per-category points use averaged positions for ties and the final display uses 1, 1, 3. Report what the code does now before changing anything.
