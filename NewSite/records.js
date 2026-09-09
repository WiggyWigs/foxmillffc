// Record Books — every table here reads directly from stats.json's
// precomputed "records" block (built by ingest_csv.py). The only
// browser-side computation is the "Average" column on the 125+ games
// table (count / seasons played), tie-aware ranking, and current-season
// highlighting — all trivial derived values that don't need their own
// precomputed fields.

async function loadRecords() {
  const wrap = document.getElementById("records-wrap");

  let data;
  try {
    const res = await fetch("data/stats.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    wrap.innerHTML = `<p class="load-state">Couldn't load stats.json (${err.message}).</p>`;
    return;
  }

  const r = data.records;
  if (!r) {
    wrap.innerHTML = `<p class="load-state">No records data found — run ingest_csv.py to generate it.</p>`;
    return;
  }

  // The season currently in progress, if any — the newest year present
  // that does NOT yet have a recorded Championship game. Once that
  // year's championship is logged, it's historical like any other and
  // nothing gets highlighted as "current" until a newer year starts.
  function getInProgressYear() {
    const years = data.games.map((g) => g.year);
    if (years.length === 0) return null;
    const latest = Math.max(...years);
    const hasChampionship = data.games.some(
      (g) => g.year === latest && g.game_type === "Championship"
    );
    return hasChampionship ? null : latest;
  }
  const inProgressYear = getInProgressYear();

  // Competition-style ranking: tied values share a rank, and the next
  // distinct value jumps to its true position (1, 1, 3 — not 1, 1, 2).
  // Returns an array of label strings, one per row, aligned by index.
  function tieAwareRanks(rows, getValue) {
    const labels = [];
    let lastValue = null;
    rows.forEach((row, i) => {
      const val = getValue(row);
      if (lastValue !== null && val === lastValue) {
        labels.push("");
      } else {
        labels.push(String(i + 1));
        lastValue = val;
      }
    });
    return labels;
  }

  // Every row tied for 1st place gets bolded, not just the physically
  // first row — index 0 plus any immediately-following rows whose rank
  // label came back blank (meaning "tied with the row above").
  function firstPlaceIndices(ranks) {
    const result = [0];
    for (let i = 1; i < ranks.length; i++) {
      if (ranks[i] === "") result.push(i);
      else break;
    }
    return result;
  }

  // A row "belongs to" the in-progress season if its own `year` field
  // matches it, or — for streak rows, which span a range — if the
  // streak's `end_year` matches (the streak was still active/ongoing
  // into the current season).
  function isCurrentSeasonRow(row) {
    if (inProgressYear === null) return false;
    if (row.year !== undefined) return row.year === inProgressYear;
    if (row.end_year !== undefined) return row.end_year === inProgressYear;
    return false;
  }

  // Renders one record section: heading + table. `cols` is an array of
  // [label, fieldNameOrFn] pairs; a function receives (row, index).
  // `rankValueFn`, if given, drives tie-aware ranking AND first-place
  // bolding. `flagIncomplete`, only true for the three average-based
  // tables (where a small sample genuinely skews the number), marks
  // under-3-season managers as "*Name" in italics — individual-game
  // and fastest-to-N tables don't get this, since a single game score
  // or a milestone reached isn't distorted by career length the way
  // an average is.
  function section(title, rows, cols, rankValueFn, flagIncomplete) {
    if (!rows || rows.length === 0) {
      return `<div class="record-section"><h3>${title}</h3><p class="load-state">No qualifying games yet.</p></div>`;
    }

    const ranks = rankValueFn ? tieAwareRanks(rows, rankValueFn) : rows.map((_, i) => String(i + 1));
    const boldRows = new Set(rankValueFn ? firstPlaceIndices(ranks) : [0]);
    const head = cols.map(([label]) =>
      `<th${label === "Manager" ? ' class="col-name"' : ""}>${label}</th>`
    ).join("");

    const body = rows.map((row, i) => {
      const seasons = data.managers[row.manager]?.career?.seasons_played ?? null;
      const incomplete = flagIncomplete && seasons !== null && seasons < 3;
      const isCurrent = isCurrentSeasonRow(row);

      const cells = cols.map(([label, get], colIdx) => {
        if (colIdx === 0) return `<td>${ranks[i]}</td>`; // rank column
        const nowrapClass = label === "Manager" ? ' class="col-name"' : "";
        if (colIdx === 1 && incomplete) return `<td${nowrapClass}><em>*${row.manager}</em></td>`; // manager column
        return `<td${nowrapClass}>${typeof get === "function" ? get(row, i) : row[get]}</td>`;
      }).join("");

      const rowClasses = [
        boldRows.has(i) ? "rank-first" : "",
        isCurrent ? "current-season-entry" : "",
      ].filter(Boolean).join(" ");

      return `<tr class="${rowClasses}">${cells}</tr>`;
    }).join("");

    return `
      <div class="record-section">
        <h3>${title}</h3>
        <table class="record-table">
          <thead><tr>${head}</tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    `;
  }

  const rankCol = ["#", null]; // value unused — rank column is handled specially in section()

  const managerYearScoreCols = [
    rankCol,
    ["Manager", "manager"],
    ["Year", "year"],
    ["Score", (row) => row.score.toFixed(2)],
  ];
  const managerYearAvgCols = [
    rankCol,
    ["Manager", "manager"],
    ["Year", "year"],
    ["Average Score", (row) => row.avg_score.toFixed(2)],
  ];
  const managerGamesCols = [
    rankCol,
    ["Manager", "manager"],
    ["Games", "games"],
  ];
  const streakCols = [
    rankCol,
    ["Manager", "manager"],
    ["Streak", (row) => `${row.streak} games`],
    ["Span", "span"],
  ];

  // "Most games above 125" / "Most games below 100" both get an extra
  // derived Average column (count ÷ seasons played), then re-sorted
  // by that average — this is the one pairing where a small sample
  // genuinely skews the number, so flagIncomplete is true for both.
  // The current in-progress season is already excluded from the raw
  // counts server-side, so no per-row highlighting applies here.
  const games125WithAvg = (r.games_above_125 || [])
    .map((e) => {
      const seasons = data.managers[e.manager]?.career?.seasons_played || 0;
      return { ...e, seasons, avgRaw: seasons ? e.count / seasons : -1 };
    })
    .sort((a, b) => b.avgRaw - a.avgRaw)
    .map((e) => ({ ...e, avg: e.seasons ? e.avgRaw.toFixed(2) : "—" }));
  const games100WithAvg = (r.games_below_100 || [])
    .map((e) => {
      const seasons = data.managers[e.manager]?.career?.seasons_played || 0;
      return { ...e, seasons, avgRaw: seasons ? e.count / seasons : -1 };
    })
    .sort((a, b) => b.avgRaw - a.avgRaw)
    .map((e) => ({ ...e, avg: e.seasons ? e.avgRaw.toFixed(2) : "—" }));
  const gamesThresholdCols = [
    rankCol,
    ["Manager", "manager"],
    ["Number of Games", "count"],
    ["Average<br>(per season)", "avg"],
  ];

  // Sections, built individually, then grouped into rows per the
  // requested a/b pairing. Titles: "Top N"/"Bottom N" counts dropped
  // (the table itself shows how many rows there are) and "Regular
  // Season" shortened to "R/S" throughout.
  const s1a = section("Average R/S Score", r.top_avg_regular_season, managerYearAvgCols, (row) => row.avg_score, false);
  const s1b = section("Lowest Average R/S Score", r.bottom_avg_regular_season, managerYearAvgCols, (row) => row.avg_score, false);
  const s2a = section("Highest R/S Game Scores", r.top_regular_season_games, managerYearScoreCols, (row) => row.score, false);
  const s2b = section("Lowest R/S Game Scores", r.bottom_regular_season_games, managerYearScoreCols, (row) => row.score, false);
  const s3a = section("Highest Playoff Game Scores", r.top_playoff_games, managerYearScoreCols, (row) => row.score, false);
  const s3b = section("Lowest Playoff Game Scores", r.bottom_playoff_games, managerYearScoreCols, (row) => row.score, false);
  const s4a = section("Games Scored Above 125 Points", games125WithAvg, gamesThresholdCols, (row) => row.avgRaw, true);
  const s4b = section("Games Scored Below 100 Points", games100WithAvg, gamesThresholdCols, (row) => row.avgRaw, true);
  const s5a = section("Fastest Manager to 25 Wins", r.fastest_to_25_wins, managerGamesCols, (row) => row.games, false);
  const s5b = section("Fastest Manager to 50 Wins", r.fastest_to_50_wins, managerGamesCols, (row) => row.games, false);
  const s6a = section("Fastest Manager to 25 Losses", r.fastest_to_25_losses, managerGamesCols, (row) => row.games, false);
  const s6b = section("Fastest Manager to 50 Losses", r.fastest_to_50_losses, managerGamesCols, (row) => row.games, false);

  // Streaks — inserted between the games-threshold pair and the
  // fastest-to-N pairs, per the requested ordering.
  const s5streak_a = section("Longest R/S Winning Streaks", r.top_winning_streaks, streakCols, (row) => row.streak, false);
  const s5streak_b = section("Longest R/S Losing Streaks", r.top_losing_streaks, streakCols, (row) => row.streak, false);

  const s5over_a = section("Longest R/S Streak Over 100 Points", r.top_over100_streaks, streakCols, (row) => row.streak, false);
  const s5over_b = section("Shortest R/S Streak Over 100 Points", r.bottom_over100_streaks, streakCols, (row) => row.streak, false);
  const s5under_a = section("Longest R/S Streak Under 100 Points", r.top_under100_streaks, streakCols, (row) => row.streak, false);
  const s5under_b = section("Shortest R/S Streak Under 100 Points", r.bottom_under100_streaks, streakCols, (row) => row.streak, false);

  const rowGroups = [
    { group: [s1a, s1b] },
    { group: [s2a, s2b] },
    { group: [s3a, s3b] },
    { group: [s4a, s4b], footnote: "*Current in-progress season not included in Games Above 125 / Below 100 counts." },
    { group: [s5streak_a, s5streak_b] },
    { group: [s5over_a, s5over_b] },
    { group: [s5under_a, s5under_b] },
    { group: [s5a, s5b] },
    { group: [s6a, s6b] },
  ];

  wrap.innerHTML = rowGroups
    .map(({ group, footnote }) => {
      const rowHtml = `<div class="record-row${group.length === 1 ? " single" : ""}">${group.join("")}</div>`;
      const footnoteHtml = footnote ? `<p class="record-footnote">${footnote}</p>` : "";
      return rowHtml + footnoteHtml;
    })
    .join("");
}

document.addEventListener("DOMContentLoaded", loadRecords);
