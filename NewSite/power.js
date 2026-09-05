// Power Rankings — reads directly from stats.json's precomputed
// "power_rankings" block (built by ingest_csv.py). Nothing computed
// in the browser; this file only renders and handles the detail modal.

async function loadPowerRankings() {
  const wrap = document.getElementById("power-wrap");
  const seasonLabel = document.getElementById("power-season-label");

  let data;
  try {
    const res = await fetch("data/stats.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    wrap.innerHTML = `<p class="load-state">Couldn't load stats.json (${err.message}).</p>`;
    return;
  }

  const pr = data.power_rankings;
  if (!pr || !pr.rankings || pr.rankings.length === 0) {
    wrap.innerHTML = `<p class="load-state">No power rankings data found yet.</p>`;
    return;
  }

  seasonLabel.textContent = `${pr.season} season strength, based on three factors weighed equally.`;

  const rows = pr.rankings; // already sorted by power_score descending

  // Competition-style ranking on power_score, matching the site's other
  // tie-aware leaderboards.
  const ranks = [];
  let lastValue = null;
  rows.forEach((row, i) => {
    if (lastValue !== null && row.power_score === lastValue) {
      ranks.push("");
    } else {
      ranks.push(String(i + 1));
      lastValue = row.power_score;
    }
  });
  const boldRows = new Set([0]);
  for (let i = 1; i < ranks.length; i++) {
    if (ranks[i] === "") boldRows.add(i);
    else break;
  }

  const fmtPct = (v) => (v * 100).toFixed(1) + "%";
  const fmtDiff = (v) => (v >= 0 ? "+" : "") + (v * 100).toFixed(1) + "%";

  let html = `
    <table class="msi-table">
      <thead>
        <tr>
          <th class="col-rank">#</th>
          <th class="col-name">Manager</th>
          <th class="col-msi">Power</th>
          <th class="num col-extra">Win%</th>
          <th class="num col-extra">Pts</th>
          <th class="num col-extra">Sched Diff</th>
        </tr>
      </thead>
      <tbody>
  `;

  rows.forEach((row, i) => {
    html += `
        <tr class="${boldRows.has(i) ? "rank-first" : ""}">
          <td class="rank-cell col-rank">${ranks[i]}</td>
          <td class="col-name msi-name-cell" tabindex="0" role="button" aria-haspopup="dialog">${row.manager}</td>
          <td class="msi-score col-msi">${row.power_score}</td>
          <td class="num col-extra">${fmtPct(row.win_pct)}</td>
          <td class="num col-extra">${row.points_scored.toFixed(1)}</td>
          <td class="num col-extra">${fmtDiff(row.schedule_difficulty)}</td>
        </tr>
    `;
  });

  html += `</tbody></table>`;
  wrap.innerHTML = html;

  setupModal(rows, fmtPct, fmtDiff);
}

function setupModal(rows, fmtPct, fmtDiff) {
  const overlay = document.getElementById("statModal");
  const closeBtn = document.getElementById("modalClose");
  let lastFocused = null;

  function openModal(rank, m) {
    document.getElementById("modalMgrName").textContent = m.manager;
    document.getElementById("modalMgrRank").textContent = `Rank #${rank}`;
    document.getElementById("modalWinPct").textContent = fmtPct(m.win_pct);
    document.getElementById("modalWinPctPts").textContent = m.win_pct_points;
    document.getElementById("modalPtsScored").textContent = m.points_scored.toFixed(2);
    document.getElementById("modalPtsScoredPts").textContent = m.points_scored_points;
    document.getElementById("modalSchedDiff").textContent = fmtDiff(m.schedule_difficulty);
    document.getElementById("modalSchedPts").textContent = m.schedule_difficulty_points;
    document.getElementById("modalPowerScore").textContent = m.power_score;
    lastFocused = document.activeElement;
    overlay.classList.add("active");
    overlay.setAttribute("aria-hidden", "false");
    closeBtn.focus();
    document.body.style.overflow = "hidden";
  }

  function closeModal() {
    overlay.classList.remove("active");
    overlay.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    if (lastFocused) lastFocused.focus();
  }

  document.querySelectorAll(".msi-name-cell").forEach((cell, i) => {
    const openThis = () => openModal(i + 1, rows[i]);
    cell.addEventListener("click", openThis);
    cell.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openThis();
      }
    });
  });

  closeBtn.addEventListener("click", closeModal);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && overlay.classList.contains("active")) closeModal();
  });
}

document.addEventListener("DOMContentLoaded", loadPowerRankings);
