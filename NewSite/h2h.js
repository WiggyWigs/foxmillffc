// Head-to-Head — "Overall Comparison" reads from stats.json's
// precomputed h2h_summary (all-time per-manager stats, deliberately
// separate from the MSI's complete-seasons-only career rollup). The
// direct matchup history between exactly two managers is computed
// here, client-side, from the raw games array — there are too many
// possible manager pairs to usefully precompute all of them server-side.

let statsData = null;

document.addEventListener("DOMContentLoaded", async () => {
  try {
    const res = await fetch("data/stats.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    statsData = await res.json();
  } catch (err) {
    document.getElementById("h2h-output").innerHTML =
      `<p class="load-state">Couldn't load stats.json (${err.message}).</p>`;
    return;
  }

  const managers = Object.keys(statsData.h2h_summary || {}).sort();
  const selA = document.getElementById("mgrA");
  const selB = document.getElementById("mgrB");
  managers.forEach((m) => {
    selA.innerHTML += `<option value="${m}">${m}</option>`;
    selB.innerHTML += `<option value="${m}">${m}</option>`;
  });

  selA.addEventListener("change", renderComparison);
  selB.addEventListener("change", renderComparison);
});

function weekSortKey(week) {
  const w = String(week);
  return w.startsWith("P") ? 100 + parseInt(w.slice(1), 10) : parseInt(w, 10);
}

function renderComparison() {
  const output = document.getElementById("h2h-output");
  const nameA = document.getElementById("mgrA").value;
  const nameB = document.getElementById("mgrB").value;

  if (!nameA || !nameB) {
    output.innerHTML = "";
    return;
  }
  if (nameA === nameB) {
    output.innerHTML = `<p class="load-state">Pick two different managers.</p>`;
    return;
  }

  const a = statsData.h2h_summary[nameA];
  const b = statsData.h2h_summary[nameB];

  const rows = [
    ["Seasons Played", a.seasons_played, b.seasons_played],
    ["Record", `${a.wins}-${a.losses}${a.ties ? "-" + a.ties : ""}`, `${b.wins}-${b.losses}${b.ties ? "-" + b.ties : ""}`],
    ["Winning %", (a.win_pct * 100).toFixed(1) + "%", (b.win_pct * 100).toFixed(1) + "%"],
    ["R/S Average Score", a.rs_avg_score.toFixed(2), b.rs_avg_score.toFixed(2)],
    ["Longest Winning Streak", `${a.longest_win_streak} games`, `${b.longest_win_streak} games`],
    ["Playoffs Made", a.playoff_appearances, b.playoff_appearances],
    ["Points Titles", a.points_titles, b.points_titles],
    ["Championships", a.championships, b.championships],
  ];

  const overallRows = rows.map(([label, va, vb]) => `
    <tr>
      <td>${va}</td>
      <td class="h2h-stat-label">${label}</td>
      <td>${vb}</td>
    </tr>
  `).join("");

  // --- Direct matchup history, computed from the raw games array ---
  const games = statsData.games.filter(
    (g) => (g.away_manager === nameA && g.home_manager === nameB)
        || (g.away_manager === nameB && g.home_manager === nameA)
  );
  games.sort((g1, g2) => {
    if (g1.year !== g2.year) return g1.year - g2.year;
    return weekSortKey(g1.week) - weekSortKey(g2.week);
  });

  let aWins = 0, bWins = 0, ties = 0, aTotal = 0, bTotal = 0;
  games.forEach((g) => {
    const aScore = g.away_manager === nameA ? g.away_score : g.home_score;
    const bScore = g.away_manager === nameB ? g.away_score : g.home_score;
    aTotal += aScore;
    bTotal += bScore;
    if (g.tie) ties++;
    else if (g.winner === nameA) aWins++;
    else bWins++;
  });
  const n = games.length;
  const aAvg = n ? (aTotal / n).toFixed(2) : "—";
  const bAvg = n ? (bTotal / n).toFixed(2) : "—";

  const h2hSummaryRows = `
    <tr>
      <td>${aWins}</td>
      <td class="h2h-stat-label">Wins</td>
      <td>${bWins}</td>
    </tr>
    <tr>
      <td>${aAvg}</td>
      <td class="h2h-stat-label">Average Score</td>
      <td>${bAvg}</td>
    </tr>
  `;

  const gamesList = games.length === 0
    ? `<p class="load-state">These two have never played each other.</p>`
    : `
      <table class="record-table h2h-games-table">
        <thead>
          <tr><th>Year</th><th>Week</th><th>${nameA}</th><th>${nameB}</th></tr>
        </thead>
        <tbody>
          ${games.map((g) => {
            const aScore = g.away_manager === nameA ? g.away_score : g.home_score;
            const bScore = g.away_manager === nameB ? g.away_score : g.home_score;
            const aWon = !g.tie && g.winner === nameA;
            const bWon = !g.tie && g.winner === nameB;
            return `
              <tr>
                <td>${g.year}</td>
                <td>${g.week}</td>
                <td class="${aWon ? "h2h-winner" : ""}">${aScore.toFixed(2)}</td>
                <td class="${bWon ? "h2h-winner" : ""}">${bScore.toFixed(2)}</td>
              </tr>
            `;
          }).join("")}
        </tbody>
      </table>
    `;

  output.innerHTML = `
    <div class="record-section">
      <h3 class="season-subhead">Overall Comparison</h3>
      <table class="record-table h2h-compare-table">
        <thead><tr><th>${nameA}</th><th></th><th>${nameB}</th></tr></thead>
        <tbody>${overallRows}</tbody>
      </table>
    </div>

    <hr class="section-divider">

    <div class="record-section">
      <h3 class="season-subhead">H2H</h3>
      <table class="record-table h2h-compare-table">
        <thead><tr><th>${nameA}</th><th></th><th>${nameB}</th></tr></thead>
        <tbody>${h2hSummaryRows}</tbody>
      </table>
      <h4 class="h2h-games-heading">Game-by-Game</h4>
      ${gamesList}
    </div>
  `;
}
