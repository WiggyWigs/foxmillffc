// Record Books — every table here reads directly from stats.json's
// precomputed "records" block (built by ingest_csv.py). The only
// browser-side computation is the "Average" column on the 125+ games
// table (count / seasons played) and tie-aware ranking, both trivial
// derived values that don't need their own precomputed fields.

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

  // Renders one record section: heading + table. `cols` is an array of
  // [label, fieldNameOrFn] pairs; a function receives (row, index).
  // `rankValueFn`, if given, drives tie-aware ranking on the first
  // column instead of plain row position. Every row is checked against
  // the manager's career seasons_played — under 3 gets italicized, and
  // a footnote appears once per table if any row qualifies.
  function section(title, rows, cols, rankValueFn) {
    if (!rows || rows.length === 0) {
      return `<div class="record-section"><h3>${title}</h3><p class="load-state">No qualifying games yet.</p></div>`;
    }

    const ranks = rankValueFn ? tieAwareRanks(rows, rankValueFn) : rows.map((_, i) => String(i + 1));
    const head = cols.map(([label]) => `<th>${label}</th>`).join("");

    const body = rows.map((row, i) => {
      const seasons = data.managers[row.manager]?.career?.seasons_played ?? null;
      const incomplete = seasons !== null && seasons < 3;

      const cells = cols.map(([label, get], colIdx) => {
        if (colIdx === 0) return `<td>${ranks[i]}</td>`; // rank column
        return `<td>${typeof get === "function" ? get(row, i) : row[get]}</td>`;
      }).join("");

      return `<tr class="${incomplete ? "incomplete-seasons" : ""}">${cells}</tr>`;
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

  // "Most games above 125" gets an extra derived Average column
  // (count ÷ seasons played), then re-sorted by that average.
  const games125WithAvg = (r.games_above_125 || [])
    .map((e) => {
      const seasons = data.managers[e.manager]?.career?.seasons_played || 0;
      return { ...e, seasons, avgRaw: seasons ? e.count / seasons : -1 };
    })
    .sort((a, b) => b.avgRaw - a.avgRaw)
    .map((e) => ({ ...e, avg: e.seasons ? e.avgRaw.toFixed(2) : "—" }));
  const games125Cols = [
    rankCol,
    ["Manager", "manager"],
    ["Number of Games", "count"],
    ["Average (Games/Seasons)", "avg"],
  ];

  // Sections, built individually, then grouped into rows per the
  // requested a/b pairing. Item 4 (125+ games) has no partner and
  // sits alone on its own row. Each call's last argument is the value
  // tie-aware ranking should compare on.
  const s1a = section("Top 10 Average Regular Season Score", r.top_avg_regular_season, managerYearAvgCols, (row) => row.avg_score);
  const s1b = section("Bottom 10 Average Regular Season Score", r.bottom_avg_regular_season, managerYearAvgCols, (row) => row.avg_score);
  const s2a = section("Top 15 Highest Regular Season Game Scores", r.top_regular_season_games, managerYearScoreCols, (row) => row.score);
  const s2b = section("Bottom 15 Lowest Regular Season Game Scores", r.bottom_regular_season_games, managerYearScoreCols, (row) => row.score);
  const s3a = section("Top 5 Highest Playoff Game Scores", r.top_playoff_games, managerYearScoreCols, (row) => row.score);
  const s3b = section("Bottom 5 Lowest Playoff Game Scores", r.bottom_playoff_games, managerYearScoreCols, (row) => row.score);
  const s4 = section("Most Games Scored Above 125 Points", games125WithAvg, games125Cols, (row) => row.avgRaw);
  const s5a = section("Fastest Manager to 25 Wins", r.fastest_to_25_wins, managerGamesCols, (row) => row.games);
  const s5b = section("Fastest Manager to 50 Wins", r.fastest_to_50_wins, managerGamesCols, (row) => row.games);
  const s6a = section("Fastest Manager to 25 Losses", r.fastest_to_25_losses, managerGamesCols, (row) => row.games);
  const s6b = section("Fastest Manager to 50 Losses", r.fastest_to_50_losses, managerGamesCols, (row) => row.games);

  const rowGroups = [
    [s1a, s1b],
    [s2a, s2b],
    [s3a, s3b],
    [s4],
    [s5a, s5b],
    [s6a, s6b],
  ];

  wrap.innerHTML = rowGroups
    .map((group) => `<div class="record-row${group.length === 1 ? " single" : ""}">${group.join("")}</div>`)
    .join("");
}

document.addEventListener("DOMContentLoaded", loadRecords);
