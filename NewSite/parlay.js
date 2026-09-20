// Parlay page — reads the precomputed data/parlays.json (built by
// scripts/sync_parlays.py from the "Parlay" Google Sheet) and does
// ALL rollup, filtering, and sorting client-side, since both need to
// respond instantly to user interaction rather than being baked in
// server-side like every other page's tables.
//
// Win/Loss record + W% only count picks whose Outcome is exactly
// "Win" or "Loss" (case-insensitive). Anything else — "Push",
// "Pending", blank, etc. — still shows up in the All Picks table but
// is excluded from the decided-games denominator, same convention
// used for win_pct everywhere else on this site (ties/undecided don't
// count toward the record).

const DATA_URL = "data/parlays.json";

let allPicks = [];

const rollupState = { year: "All", sortKey: "winPct", sortDir: "desc" };
const picksState = { year: "All", week: "All", manager: "All", sortKey: "year", sortDir: "desc" };

document.addEventListener("DOMContentLoaded", async () => {
  try {
    const res = await fetch(DATA_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    allPicks = normalizePicks(data.picks || []);
  } catch (err) {
    document.getElementById("rollup-wrap").innerHTML =
      `<p class="load-state">Couldn't load parlay data (${err.message}).</p>`;
    document.getElementById("picks-wrap").innerHTML = "";
    return;
  }

  if (allPicks.length === 0) {
    document.getElementById("rollup-wrap").innerHTML =
      `<p class="load-state">No parlay picks recorded yet.</p>`;
    document.getElementById("picks-wrap").innerHTML = "";
    return;
  }

  populateFilterOptions();
  wireFilterEvents();
  renderRollup();
  renderPicks();
});

function normalizePicks(rawPicks) {
  return rawPicks.map((p) => ({
    year: Number(p.year),
    week: p.week,
    weekNum: parseWeek(p.week),
    manager: p.manager,
    bet: p.bet,
    odds: p.odds,
    oddsNum: parseOdds(p.odds),
    outcome: p.outcome,
    outcomeNorm: String(p.outcome || "").trim().toLowerCase(),
  }));
}

function parseWeek(week) {
  const n = parseInt(String(week).replace(/[^\d]/g, ""), 10);
  return Number.isNaN(n) ? 0 : n;
}

function parseOdds(odds) {
  if (odds == null) return 0;
  const n = parseInt(String(odds).replace(/[^-\d]/g, ""), 10);
  return Number.isNaN(n) ? 0 : n;
}

function isWin(p) { return p.outcomeNorm === "win" || p.outcomeNorm === "w"; }
function isLoss(p) { return p.outcomeNorm === "loss" || p.outcomeNorm === "lose" || p.outcomeNorm === "l"; }

function uniqueSortedNumbers(arr) {
  return [...new Set(arr)].sort((a, b) => a - b);
}

function populateFilterOptions() {
  const years = uniqueSortedNumbers(allPicks.map((p) => p.year)).reverse();
  const weeks = uniqueSortedNumbers(allPicks.map((p) => p.weekNum));
  const managers = [...new Set(allPicks.map((p) => p.manager))].sort((a, b) => a.localeCompare(b));

  fillSelect("rollupYearFilter", years);
  fillSelect("pickYearFilter", years);
  fillSelect("pickWeekFilter", weeks);
  fillSelect("pickManagerFilter", managers);
}

function fillSelect(id, values) {
  const sel = document.getElementById(id);
  if (!sel) return;
  values.forEach((v) => {
    const opt = document.createElement("option");
    opt.value = String(v);
    opt.textContent = String(v);
    sel.appendChild(opt);
  });
}

function wireFilterEvents() {
  document.getElementById("rollupYearFilter").addEventListener("change", (e) => {
    rollupState.year = e.target.value;
    renderRollup();
  });
  document.getElementById("pickYearFilter").addEventListener("change", (e) => {
    picksState.year = e.target.value;
    renderPicks();
  });
  document.getElementById("pickWeekFilter").addEventListener("change", (e) => {
    picksState.week = e.target.value;
    renderPicks();
  });
  document.getElementById("pickManagerFilter").addEventListener("change", (e) => {
    picksState.manager = e.target.value;
    renderPicks();
  });
}

// --- Shared sort helpers ---

function sortRows(rows, key, dir, columns) {
  const col = columns.find((c) => c.key === key) || columns[0];
  return [...rows].sort((a, b) => {
    const cmp = col.type === "number"
      ? (a[col.key] ?? 0) - (b[col.key] ?? 0)
      : String(a[col.key] ?? "").localeCompare(String(b[col.key] ?? ""), undefined, { sensitivity: "base" });
    return dir === "asc" ? cmp : -cmp;
  });
}

function renderSortableHeader(col, state) {
  const active = state.sortKey === col.key;
  const arrow = active ? (state.sortDir === "asc" ? "▲" : "▼") : "";
  return `<th class="sortable-th" data-sort-key="${col.key}">${col.label}${arrow ? ` <span class="sort-indicator">${arrow}</span>` : ""}</th>`;
}

function attachHeaderHandlers(wrap, columns, state, renderFn) {
  wrap.querySelectorAll(".sortable-th").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sortKey;
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        const col = columns.find((c) => c.key === key);
        state.sortKey = key;
        state.sortDir = col && col.type === "number" ? "desc" : "asc";
      }
      renderFn();
    });
  });
}

// --- Parlay Standings (rollup) ---

const ROLLUP_COLUMNS = [
  { key: "manager", label: "Manager", type: "string" },
  { key: "wins", label: "W", type: "number" },
  { key: "losses", label: "L", type: "number" },
  { key: "winPct", label: "W%", type: "number" },
];

function computeRollup(picks) {
  const byManager = new Map();
  picks.forEach((p) => {
    if (!byManager.has(p.manager)) {
      byManager.set(p.manager, { manager: p.manager, wins: 0, losses: 0, other: 0 });
    }
    const m = byManager.get(p.manager);
    if (isWin(p)) m.wins++;
    else if (isLoss(p)) m.losses++;
    else m.other++;
  });
  return Array.from(byManager.values()).map((m) => {
    const decided = m.wins + m.losses;
    return { ...m, winPct: decided ? m.wins / decided : 0 };
  });
}

function renderRollup() {
  const wrap = document.getElementById("rollup-wrap");
  const filtered = rollupState.year === "All"
    ? allPicks
    : allPicks.filter((p) => String(p.year) === String(rollupState.year));

  if (filtered.length === 0) {
    wrap.innerHTML = `<p class="load-state">No parlay picks for this year.</p>`;
    return;
  }

  const rows = sortRows(computeRollup(filtered), rollupState.sortKey, rollupState.sortDir, ROLLUP_COLUMNS);
  const headerCells = ROLLUP_COLUMNS.map((col) => renderSortableHeader(col, rollupState)).join("");

  const bodyRows = rows.map((r) => `
    <tr>
      <td class="col-name">${r.manager}</td>
      <td>${r.wins}</td>
      <td>${r.losses}</td>
      <td>${(r.winPct * 100).toFixed(1)}%</td>
    </tr>
  `).join("");

  wrap.innerHTML = `
    <div class="table-scroll">
      <table class="record-table parlay-rollup-table">
        <thead><tr>${headerCells}</tr></thead>
        <tbody>${bodyRows}</tbody>
      </table>
    </div>
  `;

  attachHeaderHandlers(wrap, ROLLUP_COLUMNS, rollupState, renderRollup);
}

// --- All Picks table ---

const PICK_COLUMNS = [
  { key: "year", label: "Year", type: "number" },
  { key: "weekNum", label: "Week", type: "number" },
  { key: "manager", label: "Manager", type: "string" },
  { key: "bet", label: "Bet", type: "string" },
  { key: "oddsNum", label: "Odds", type: "number" },
  { key: "outcome", label: "Outcome", type: "string" },
];

function renderPicks() {
  const wrap = document.getElementById("picks-wrap");
  let filtered = allPicks;
  if (picksState.year !== "All") filtered = filtered.filter((p) => String(p.year) === String(picksState.year));
  if (picksState.week !== "All") filtered = filtered.filter((p) => String(p.weekNum) === String(picksState.week));
  if (picksState.manager !== "All") filtered = filtered.filter((p) => p.manager === picksState.manager);

  if (filtered.length === 0) {
    wrap.innerHTML = `<p class="load-state">No picks match these filters.</p>`;
    return;
  }

  const rows = sortRows(filtered, picksState.sortKey, picksState.sortDir, PICK_COLUMNS);
  const headerCells = PICK_COLUMNS.map((col) => renderSortableHeader(col, picksState)).join("");

  const bodyRows = rows.map((p) => `
    <tr>
      <td>${p.year}</td>
      <td>${p.week}</td>
      <td class="col-name">${p.manager}</td>
      <td class="parlay-bet-cell">${p.bet}</td>
      <td>${p.odds}</td>
      <td>${p.outcome}</td>
    </tr>
  `).join("");

  wrap.innerHTML = `
    <div class="table-scroll">
      <table class="record-table parlay-picks-table">
        <thead><tr>${headerCells}</tr></thead>
        <tbody>${bodyRows}</tbody>
      </table>
    </div>
  `;

  attachHeaderHandlers(wrap, PICK_COLUMNS, picksState, renderPicks);
}
