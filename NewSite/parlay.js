// Parlay page — fetches the "Parlay" Google Sheet directly from the
// browser (it's published to the web as CSV) and does ALL parsing,
// rollup, filtering, and sorting client-side. No server-side sync
// step and no data/parlays.json: this is the one page on the site
// that reads live from an external source instead of a precomputed
// local data/*.json file, by deliberate choice — standings reflect a
// sheet edit the moment the page is reloaded, at the cost of page
// load depending on Google's endpoint responding (with CORS headers
// that allow a browser fetch — this works today but isn't a
// documented guarantee from Google). If this page ever starts
// silently failing to load, that's the first thing to check: confirm
// the sheet is still Published to the web (File > Share > Publish to
// web > CSV) and that SHEET_CSV_URL below still matches its URL.
//
// Win/Loss record + W% only count picks whose Outcome is exactly
// "Win" or "Loss" (case-insensitive). Anything else — "Push",
// "Pending", blank, etc. — still shows up in the All Picks table but
// is excluded from the decided-games denominator, same convention
// used for win_pct everywhere else on this site (ties/undecided don't
// count toward the record).
//
// ASSWIPE (Adjusted Standardized Score - Weighted Individual Parlay
// Evaluator) = PISS + (Winning Differential / 10), where:
//   PISS  = Win% (decimal, 0-1) x Average Odds
//   Winning Differential = Total Wins - Total Losses
// Average Odds is the mean of the raw signed Odds value (e.g. +450,
// -110), decimals preserved, across EVERY pick in the current time
// frame, win or lose — not just the winning ones. Everything here
// respects the Parlay Standings table's own Year filter, same as
// W/L/W% already did.
//
// Odds display: every Odds value (Avg Odds in Standings, Odds in All
// Picks) is formatted to exactly two decimal places. The sign
// character shown (+/-/none) is taken from however each row's raw
// Odds text was actually entered — a computed average always shows
// an explicit sign, since it isn't tied to one row's original text.
//
// Every "Name" value is checked against data/manager_roster.json (the
// same roster file every other page uses). An unrecognized name is
// dropped rather than creating a new, misspelled entry in the Parlay
// Standings table — but since this now runs in each visitor's
// browser, that rejection only shows up as a console.warn in
// DevTools, not anywhere Greg would normally see it. Worth an
// occasional manual check of the sheet against the roster.

const SHEET_CSV_URL =
  "https://docs.google.com/spreadsheets/d/e/2PACX-1vT9gbWRe2LfduGjbKHt5cWdq8p2LT_vTXgDkCJetDh3v-5cDD2LA5NBI4Du-7n7VGnZolw-DbcsyeRG/pub?gid=0&single=true&output=csv";
const ROSTER_URL = "data/manager_roster.json";

let allPicks = [];

const rollupState = { year: "All", sortKey: "asswipe", sortDir: "desc" };
const picksState = { year: "All", week: "All", manager: "All", sortKey: "year", sortDir: "desc" };

document.addEventListener("DOMContentLoaded", async () => {
  let csvText, roster;
  try {
    const [csvRes, rosterRes] = await Promise.all([
      fetch(SHEET_CSV_URL),
      fetch(ROSTER_URL),
    ]);
    if (!csvRes.ok) throw new Error(`sheet fetch HTTP ${csvRes.status}`);
    if (!rosterRes.ok) throw new Error(`roster fetch HTTP ${rosterRes.status}`);
    csvText = await csvRes.text();
    const rosterJson = await rosterRes.json();
    roster = new Set(rosterJson.managers || []);
  } catch (err) {
    document.getElementById("rollup-wrap").innerHTML =
      `<p class="load-state">Couldn't load parlay data (${err.message}). If this keeps happening, ` +
      `confirm the sheet is still Published to the web (File &gt; Share &gt; Publish to web) as CSV.</p>`;
    document.getElementById("picks-wrap").innerHTML = "";
    return;
  }

  allPicks = normalizePicks(parseCsvRows(csvText), roster);

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

// --- CSV parsing (minimal RFC4180: quoted fields, embedded commas,
// escaped "" quotes, \r\n or \n line endings) ---

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else { inQuotes = false; }
      } else {
        field += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += c;
    }
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

function parseCsvRows(text) {
  const table = parseCsv(text);
  if (table.length === 0) return [];
  const headers = table[0].map((h) => h.trim());
  return table.slice(1)
    .filter((r) => r.some((cell) => cell.trim() !== ""))
    .map((r) => Object.fromEntries(headers.map((h, idx) => [h, (r[idx] ?? "").trim()])));
}

// --- Row validation + normalization ---

function normalizePicks(rows, roster) {
  const picks = [];
  rows.forEach((row, idx) => {
    const yearRaw = row["Year"] || "";
    const weekRaw = row["Week"] || "";
    const name = row["Name"] || "";
    const bet = row["Bet"] || "";
    const odds = row["Odds"] || "";
    const outcome = row["Outcome"] || "";
    const rowNum = idx + 2; // +1 for header row, +1 for 1-indexing

    if (!yearRaw || !weekRaw || !name || !bet) {
      console.warn(`Parlay sheet row ${rowNum}: missing Year/Week/Name/Bet — skipped.`);
      return;
    }
    if (roster.size > 0 && !roster.has(name)) {
      console.warn(`Parlay sheet row ${rowNum}: '${name}' isn't a recognized manager — skipped.`);
      return;
    }
    const year = Number(yearRaw);
    if (Number.isNaN(year)) {
      console.warn(`Parlay sheet row ${rowNum}: Year '${yearRaw}' isn't a number — skipped.`);
      return;
    }

    picks.push({
      year,
      week: weekRaw,
      weekNum: parseWeek(weekRaw),
      manager: name,
      bet,
      odds,
      oddsNum: parseOdds(odds),
      outcome,
      outcomeNorm: outcome.trim().toLowerCase(),
    });
  });
  return picks;
}

function parseWeek(week) {
  const n = parseInt(String(week).replace(/[^\d]/g, ""), 10);
  return Number.isNaN(n) ? 0 : n;
}

// Decimal-aware: preserves a leading +/- sign and any decimal portion
// (parseInt would silently truncate "4.5" down to 4). Used both for
// sorting and for every Avg Odds / PISS / ASSWIPE calculation.
function parseOdds(odds) {
  if (odds == null) return 0;
  const s = String(odds).trim();
  if (!s) return 0;
  const n = parseFloat(s.replace(/[^0-9.+-]/g, ""));
  return Number.isNaN(n) ? 0 : n;
}

// Display-only formatter: shows exactly two decimal places, keeping
// whichever sign character (if any) was actually typed in the sheet
// rather than inventing one — a "+" only appears if the raw text had
// one, so this doesn't misrepresent decimal-odds data as American
// odds or vice versa.
function formatOddsDisplay(oddsRaw) {
  const s = String(oddsRaw || "").trim();
  if (!s) return s;
  const sign = s[0] === "+" || s[0] === "-" ? s[0] : "";
  const magnitude = parseFloat(s.replace(/[^0-9.]/g, ""));
  if (Number.isNaN(magnitude)) return s; // unparsable — show the raw text rather than mangling it
  return sign + magnitude.toFixed(2);
}

// Computed averages aren't tied to one row's original text, so they
// always show an explicit sign for readability.
function formatOddsSigned(n) {
  return (n >= 0 ? "+" : "") + n.toFixed(2);
}

function isWin(p) { return p.outcomeNorm === "win" || p.outcomeNorm === "w"; }
function isLoss(p) { return p.outcomeNorm === "loss" || p.outcomeNorm === "lose" || p.outcomeNorm === "l"; }

function uniqueSortedNumbers(arr) {
  return [...new Set(arr)].sort((a, b) => a - b);
}

// Preserves any non-numeric Week values (e.g. "Playoffs") as their
// own distinct filter options instead of collapsing them all down to
// a single numeric bucket — numeric weeks sort first and ascending,
// text values follow, alphabetically.
function uniqueSortedWeeks(picks) {
  const values = [...new Set(picks.map((p) => String(p.week)))];
  const isNumeric = (v) => /^-?\d+(\.\d+)?$/.test(v.trim());
  const nums = values.filter(isNumeric).sort((a, b) => parseFloat(a) - parseFloat(b));
  const text = values.filter((v) => !isNumeric(v)).sort((a, b) => a.localeCompare(b));
  return [...nums, ...text];
}

function populateFilterOptions() {
  const years = uniqueSortedNumbers(allPicks.map((p) => p.year)).reverse();
  const weeks = uniqueSortedWeeks(allPicks);
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
  { key: "avgOdds", label: "Avg Odds", type: "number" },
  { key: "asswipe", label: "ASSWIPE", type: "number" },
];

function computeRollup(picks) {
  const byManager = new Map();
  picks.forEach((p) => {
    if (!byManager.has(p.manager)) {
      byManager.set(p.manager, {
        manager: p.manager, wins: 0, losses: 0, other: 0,
        totalOdds: 0, totalPicks: 0,
      });
    }
    const m = byManager.get(p.manager);
    if (isWin(p)) m.wins++;
    else if (isLoss(p)) m.losses++;
    else m.other++;
    m.totalOdds += p.oddsNum;
    m.totalPicks++;
  });
  return Array.from(byManager.values()).map((m) => {
    const decided = m.wins + m.losses;
    const winPct = decided ? m.wins / decided : 0;
    const avgOdds = m.totalPicks ? m.totalOdds / m.totalPicks : 0;
    const winningDifferential = m.wins - m.losses;
    const piss = winPct * avgOdds;
    const asswipe = piss + (winningDifferential / 10);
    return { ...m, winPct, avgOdds, winningDifferential, piss, asswipe };
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
      <td>${formatOddsSigned(r.avgOdds)}</td>
      <td class="msi-score">${r.asswipe.toFixed(2)}</td>
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
  if (picksState.week !== "All") filtered = filtered.filter((p) => String(p.week) === String(picksState.week));
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
      <td>${formatOddsDisplay(p.odds)}</td>
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
