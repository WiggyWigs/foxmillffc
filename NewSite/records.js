// Record Books — every table here reads directly from stats.json's
// precomputed "records" block (built by ingest_csv.py). Nothing is
// computed in the browser; this file only renders.

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
  // [label, fieldNameOrFn] pairs, evaluated per row.
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
    const body = rows.map((row) => {
      const cells = cols.map(([, get]) =>
        `<td>${typeof get === "function" ? get(row) : row[get]}</td>`
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

  const managerYearScoreCols = [
    ["Manager", "manager"],
    ["Year", "year"],
    ["Score", (row) => row.score.toFixed(2)],
  ];
  const managerYearAvgCols = [
    ["Manager", "manager"],
    ["Year", "year"],
    ["Average Score", (row) => row.avg_score.toFixed(2)],
  ];
  const managerGamesCols = [
    ["Manager", "manager"],
    ["Games", "games"],
  ];

  // Rendered in the exact order requested.
  const html = [
    section("Top 10 Average Regular Season Score", r.top_avg_regular_season, managerYearAvgCols),
    section("Bottom 10 Average Regular Season Score", r.bottom_avg_regular_season, managerYearAvgCols),
    section("Top 15 Highest Regular Season Game Scores", r.top_regular_season_games, managerYearScoreCols),
    section("Bottom 15 Lowest Regular Season Game Scores", r.bottom_regular_season_games, managerYearScoreCols),
    section("Top 5 Highest Playoff Game Scores", r.top_playoff_games, managerYearScoreCols),
    section("Bottom 5 Lowest Playoff Game Scores", r.bottom_playoff_games, managerYearScoreCols),
    section("Most Games Scored Above 125 Points", r.games_above_125, [
      ["Manager", "manager"], ["Number of Games", "count"],
    ]),
    section("Fastest Manager to 25 Wins", r.fastest_to_25_wins, managerGamesCols),
    section("Fastest Manager to 50 Wins", r.fastest_to_50_wins, managerGamesCols),
    section("Fastest Manager to 25 Losses", r.fastest_to_25_losses, managerGamesCols),
    section("Fastest Manager to 50 Losses", r.fastest_to_50_losses, managerGamesCols),
  ].join("");

  wrap.innerHTML = html;
}

document.addEventListener("DOMContentLoaded", loadRecords);
