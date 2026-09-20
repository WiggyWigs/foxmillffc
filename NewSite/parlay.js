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
// A row only counts — anywhere on this page — if it has BOTH a
// non-empty Odds value AND a decided Outcome ("Win" or "Loss",
// case-insensitive). A row missing either one is dropped entirely: it
// never appears in the All Picks table and never enters any Standings
// math (W, L, W%, Avg Odds, PISS, Winning Differential, ASSWIPE).
// "Push", "Pending", blank Outcome, or blank Odds are all treated the
// same way — excluded, not just uncounted. (This is a stricter rule
// than the old "ties don't count toward the record" convention used
// elsewhere on the site: here the whole row disappears, not just its
// contribution to the decided-games denominator.)
//
// ASSWIPE (Adjusted Standardized Score - Weighted Individual Parlay
// Evaluator) = PISS + (Winning Differential / 10), where:
//   PISS  = Win% (decimal, 0-1) x Average Odds
//   Winning Differential = Total Wins - Total Losses
// Average Odds is the mean of the raw signed Odds value (e.g. +450,
// -110), decimals preserved, across every counted pick in the current
// time frame, win or lose — not just the winning ones. Everything
// here respects the Parlay Standings table's own Year filter, same as
// W/L/W% already did.
//
// Odds display, two DIFFERENT rules on purpose:
//   - All Picks' Odds column shows each row's raw sheet text,
//     reformatted to exactly two decimal places but keeping whatever
//     sign character (+/-/none) was actually typed — that's someone's
//     literal entry, not a computed value, so it isn't second-guessed.
//   - Standings' Avg Odds column is a computed average, never shows a
//     "+" — just the magnitude to two decimals, with a "-" only when
//     the average is actually negative (toFixed already supplies that,
//     nothing extra added).
//
// Week column ("Week" filter + sort in All Picks) uses a NATURAL sort,
// not a plain text or plain numeric one: values like "13",
// "13a - Thanksgiving", "14" sort as 13, 13a - Thanksgiving, 14 —
// by leading number first, then by whatever text follows it — no
// matter what order those rows happen to sit in on the sheet itself.
// A week with no leading number at all (e.g. "Playoffs") sorts after
// every numbered week.
//
// Every "Name" value is checked against data/manager_roster.json (the
// same roster file every other page uses). An unrecognized name is
// dropped rather than creating a new, misspelled entry in the Parlay
// Standings table — but since this now runs in each visitor's
// browser, that rejection only shows up as a console.warn in
// DevTools, not anywhere Greg would normally see it. Worth an
// occasional manual check of the sheet against the roster.
//
// Avg Odds and ASSWIPE column headers each render TWO versions: a
// one-line ".th-label-desktop" span ("Avg Odds" / "ASSWIPE") and a
// stacked ".th-label-mobile" span ("Avg" / "Odds" and "ASS-" /
// "WIPE" on two lines). CSS toggles which one is visible — the mobile
// version only shows up in narrow portrait view, where the one-line
// versions were overlapping the neighboring column.

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

    // A pick only counts if it has BOTH a non-empty Odds value and a
    // decided Win/Loss Outcome. Missing either one drops the row
    // entirely — not shown in All Picks, not counted in any Standings
    // math. "Push"/"Pending"/blank Outcome and blank Odds are all
    // treated the same: excluded.
    const outcomeNorm = outcome.trim().toLowerCase();
    const hasOdds = odds.trim() !== "";
    const hasDecision = outcomeNorm === "win" || outcomeNorm === "w" ||
      outcomeNorm === "loss" || outcomeNorm === "lose" || outcomeNorm === "l";
    if (!hasOdds || !hasDecision) {
      console.warn(`Parlay sheet row ${rowNum}: needs both an Odds value and a decided Win/Loss Outcome — excluded from display and calculations.`);
      return;
    }

    picks.push({
      year,
      week: weekRaw,
      manager: name,
      bet,
      odds,
      oddsNum: parseOdds(odds),
      outcome,
      outcomeNorm,
    });
  });
  return picks;
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

// All Picks' Odds column: reformats a row's raw Odds text to exactly
// two decimal places, keeping whichever sign character (if any) was
// actually typed in the sheet — someone's literal entry, not second-
// guessed.
function formatOddsRaw(oddsRaw) {
  const s = String(oddsRaw || "").trim();
  if (!s) return s;
  const sign = s[0] === "+" || s[0] === "-" ? s[0] : "";
  const magnitude = parseFloat(s.replace(/[^0-9.]/g, ""));
  if (Number.isNaN(magnitude)) return s; // unparsable — show the raw text rather than mangling it
  return sign + magnitude.toFixed(2);
}

// Standings' Avg Odds column: a computed average, never shown with a
// "+" — just the magnitude to two decimals. A negative average still
// shows its "-" (toFixed(2) supplies that on its own; nothing added).
function formatOddsAvg(n) {
  return n.toFixed(2);
}

function isWin(p) { return p.outcomeNorm === "win" || p.outcomeNorm === "w"; }
function isLoss(p) { return p.outcomeNorm === "loss" || p.outcomeNorm === "lose" || p.outcomeNorm === "l"; }

function uniqueSortedNumbers(arr) {
  return [...new Set(arr)].sort((a, b) => a - b);
}

// --- Natural sort for the Week column ---
// Splits a week value into its leading number (if any) and whatever
// text trails it, e.g. "13a - Thanksgiving" -> {num: 13, suffix: "a -
// Thanksgiving"}. A bare "13" gets suffix "", which always sorts
// before a non-empty suffix at the same number — so "13" comes right
// before "13a - Thanksgiving", which comes right before "14". A week
// with no leading number at all sorts after every numbered week.
function parseWeekSortKey(week) {
  const s = String(week).trim();
  const m = s.match(/^(\d+(?:\.\d+)?)/);
  if (m) {
    return { num: parseFloat(m[1]), suffix: s.slice(m[0].length).trim() };
  }
  return { num: Infinity, suffix: s };
}

function compareWeek(weekA, weekB) {
  const a = parseWeekSortKey(weekA);
  const b = parseWeekSortKey(weekB);
  if (a.num !== b.num) return a.num - b.num;
  return a.suffix.localeCompare(b.suffix, undefined, { sensitivity: "base" });
}

// Unique Week values for the filter dropdown, in the same natural
// order as the table itself uses — so a text week like
// "13a - Thanksgiving" shows up between "13" and "14" in the dropdown
// too, not shoved to the end.
function uniqueSortedWeeks(picks) {
  const values = [...new Set(picks.map((p) => String(p.week)))];
  return values.sort(compareWeek);
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
    let cmp;
    if (col.type === "number") {
      cmp = (a[col.key] ?? 0) - (b[col.key] ?? 0);
    } else if (col.type === "natural-week") {
      cmp = compareWeek(a[col.key], b[col.key]);
    } else {
      cmp = String(a[col.key] ?? "").localeCompare(String(b[col.key] ?? ""), undefined, { sensitivity: "base" });
    }
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
  { key: "avgOdds", label: '<span class="th-label-desktop">Avg Odds</span><span class="th-label-mobile">Avg<br>Odds</span>', type: "number" },
  { key: "asswipe", label: '<span class="th-label-desktop">ASSWIPE</span><span class="th-label-mobile">ASS-<br>WIPE</span>', type: "number" },
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
      <td>${formatOddsAvg(r.avgOdds)}</td>
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
  { key: "week", label: "Week", type: "natural-week" },
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
      <td>${formatOddsRaw(p.odds)}</td>
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
