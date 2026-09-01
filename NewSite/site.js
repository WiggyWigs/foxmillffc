// Manager Score Index rendering.
//
// NOTE: fetch() of a local file only works when this site is served over
// http:// (a local dev server, or once hosted on GitHub Pages / any web
// host). Opening index.html directly via file:// will fail silently in
// most browsers due to CORS restrictions on local file access. If you're
// testing locally, run something like:
//     python3 -m http.server 8000
// from inside the site/ folder, then visit http://localhost:8000/

async function loadManagerScoreIndex() {
  const wrap = document.getElementById("table-wrap");
  const updatedEl = document.getElementById("last-updated");

  let data;
  try {
    const res = await fetch("data/stats.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    wrap.innerHTML = `<p class="load-state">Couldn't load stats.json (${err.message}). ` +
      `If you're viewing this file directly from disk, run a local server instead ` +
      `&mdash; see the comment at the top of site.js.</p>`;
    return;
  }

  if (updatedEl) {
    updatedEl.textContent = data.last_updated ? `updated ${data.last_updated}` : "";
  }

  const rows = Object.entries(data.managers)
    .map(([name, d]) => ({ name, ...d.career }))
    .sort((a, b) => b.manager_score_index - a.manager_score_index);

  const fmtPct = (v) => (v * 100).toFixed(1) + "%";

  let html = `
    <table class="msi-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Manager</th>
          <th>MSI</th>
          <th class="num">Seasons</th>
          <th class="num">Reg. Win%</th>
          <th class="num">Playoff Win%</th>
          <th class="num">Playoff Apps</th>
          <th class="num">Champs</th>
          <th class="num">Runner-ups</th>
          <th class="num">Pts Titles</th>
        </tr>
      </thead>
      <tbody>
  `;

  rows.forEach((m, i) => {
    html += `
        <tr>
          <td class="rank-cell">${i + 1}</td>
          <td>${m.name}</td>
          <td class="msi-score">${m.manager_score_index.toFixed(3)}</td>
          <td class="num">${m.seasons_played}</td>
          <td class="num">${fmtPct(m.regular_season_win_pct)}</td>
          <td class="num">${fmtPct(m.playoff_win_pct)}</td>
          <td class="num">${m.playoff_appearances}</td>
          <td class="num">${m.championships}</td>
          <td class="num">${m.runner_ups}</td>
          <td class="num">${m.points_titles}</td>
        </tr>
    `;
  });

  html += `</tbody></table>`;
  wrap.innerHTML = html;
}

document.addEventListener("DOMContentLoaded", loadManagerScoreIndex);
