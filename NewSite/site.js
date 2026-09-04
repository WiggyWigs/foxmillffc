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
  const AVERAGE_JOE_LINE = 2.383;

  let html = `
    <table class="msi-table">
      <thead>
        <tr>
          <th class="col-rank">#</th>
          <th class="col-name">Manager</th>
          <th class="col-msi">MSI</th>
          <th class="num col-extra">Seasons</th>
          <th class="num col-extra">Reg. Win%</th>
          <th class="num col-extra">Playoff Win%</th>
          <th class="num col-extra">Playoff Apps</th>
          <th class="num col-extra">Champs</th>
          <th class="num col-extra">Runner-ups</th>
          <th class="num col-extra">Pts Titles</th>
        </tr>
      </thead>
      <tbody>
  `;

  // Insert the Average Joe Line divider row at the point where MSI scores
  // cross below the threshold — computed fresh each load since rankings
  // shift week to week, never hardcoded to a row index.
  let joeLineInserted = false;

  rows.forEach((m, i) => {
    if (!joeLineInserted && m.manager_score_index < AVERAGE_JOE_LINE) {
      html += `
        <tr class="average-joe-row">
          <td colspan="10">Average Joe Line &mdash; ${AVERAGE_JOE_LINE}</td>
        </tr>
      `;
      joeLineInserted = true;
    }

    html += `
        <tr>
          <td class="rank-cell col-rank">${i + 1}</td>
          <td class="col-name msi-name-cell" tabindex="0" role="button" aria-expanded="false">${m.name}</td>
          <td class="msi-score col-msi">${m.manager_score_index.toFixed(3)}</td>
          <td class="num col-extra" data-label="Seasons">${m.seasons_played}</td>
          <td class="num col-extra" data-label="Reg. Win%">${fmtPct(m.regular_season_win_pct)}</td>
          <td class="num col-extra" data-label="Playoff Win%">${fmtPct(m.playoff_win_pct)}</td>
          <td class="num col-extra" data-label="Playoff Apps">${m.playoff_appearances}</td>
          <td class="num col-extra" data-label="Champs">${m.championships}</td>
          <td class="num col-extra" data-label="Runner-ups">${m.runner_ups}</td>
          <td class="num col-extra" data-label="Pts Titles">${m.points_titles}</td>
        </tr>
    `;
  });

  html += `</tbody></table>`;
  wrap.innerHTML = html;

  // Mobile: tapping/clicking a manager's name reveals their remaining
  // stats (hidden by default at narrow widths via CSS). No effect on
  // desktop, where col-extra cells are already visible.
  wrap.querySelectorAll(".msi-name-cell").forEach((cell) => {
    const toggle = () => {
      const row = cell.closest("tr");
      const isOpen = row.classList.toggle("row-expanded");
      cell.setAttribute("aria-expanded", isOpen ? "true" : "false");
    };
    cell.addEventListener("click", toggle);
    cell.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggle();
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", loadManagerScoreIndex);
