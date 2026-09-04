// Record Books — every table here reads directly from stats.json's
// precomputed "records" block (built by ingest_csv.py). Nothing is
// computed in the browser except the "Average" column on the 125+
// games table, which is a trivial derived value (count / seasons
// played) that doesn't need its own precomputed field.

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

  // Renders one record section: a heading plus a table built from
  // `rows` using the given column definitions. `cols` is an array of
  // [label, fieldNameOrFn] pairs; a function receives (row, index) so
  // columns like rank can be derived from position rather than data.
  function section(title, rows, cols) {
    if (!rows || rows.length === 0) {
      return `
        <div class="record-section">
          <h3>${title}</h3>
          <p class="load-state">No qualifying games yet.</p>
        </div>
      `;
    }
    const head = cols.map(([label]) => `<th>${label}</th>`).join("");
    const body = rows.map((row, i) => {
      const cells = cols.map(([, get]) =>
        `<td>${typeof get === "function" ? get(row, i) : row[get]}</td>`
      ).join("");
      return `<tr>${cells}</tr>`;
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

  const rankCol = ["#", (row, i) => i + 1];

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
  // (count ÷ seasons played) — trivial enough not to need its own
  // precomputed field in stats.json, just a lookup against career data.
  const games125WithAvg = (r.games_above_125 || []).map((e) => {
    const seasons = data.managers[e.manager]?.career?.seasons_played || 0;
    return {
      ...e,
      seasons,
      avg: seasons ? (e.count / seasons).toFixed(2) : "—",
    };
  });
  const games125Cols = [
    rankCol,
    ["Manager", "manager"],
    ["Number of Games", "count"],
    ["Average (Games/Seasons)", "avg"],
  ];

  // Sections, built individually, then grouped into rows per the
  // requested a/b pairing. Item 4 (125+ games) has no partner and
  // sits alone on its own row.
  const s1a = section("Top 10 Average Regular Season Score", r.top_avg_regular_season, managerYearAvgCols);
  const s1b = section("Bottom 10 Average Regular Season Score", r.bottom_avg_regular_season, managerYearAvgCols);
  const s2a = section("Top 15 Highest Regular Season Game Scores", r.top_regular_season_games, managerYearScoreCols);
  const s2b = section("Bottom 15 Lowest Regular Season Game Scores", r.bottom_regular_season_games, managerYearScoreCols);
  const s3a = section("Top 5 Highest Playoff Game Scores", r.top_playoff_games, managerYearScoreCols);
  const s3b = section("Bottom 5 Lowest Playoff Game Scores", r.bottom_playoff_games, managerYearScoreCols);
  const s4 = section("Most Games Scored Above 125 Points", games125WithAvg, games125Cols);
  const s5a = section("Fastest Manager to 25 Wins", r.fastest_to_25_wins, managerGamesCols);
  const s5b = section("Fastest Manager to 50 Wins", r.fastest_to_50_wins, managerGamesCols);
  const s6a = section("Fastest Manager to 25 Losses", r.fastest_to_25_losses, managerGamesCols);
  const s6b = section("Fastest Manager to 50 Losses", r.fastest_to_50_losses, managerGamesCols);

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
