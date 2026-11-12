// Draft Board page — who owns every pick in a draft, as a grid: managers
// across the top (the pick's ORIGINAL owner), rounds down the side, each
// cell showing who holds that pick now in that manager's color.
//
// Data comes straight from two Google Sheets tabs, published to the web
// as CSV (File > Share > Publish to web), fetched on every page load like
// the Parlay page — so a sheet edit shows up on reload, no site update.
//
//   Trade Log  (TRADE_LOG_CSV_URL): one row per pick changing hands.
//     Order, Year, Round, Original Owner, From, To, Player
//     Order groups the picks in one trade (same number = same trade) and
//     orders trades (higher = later). A pick is identified by Year + Round
//     + Original Owner; its holder is the To of its last row. Each row's
//     From must be whoever held the pick before it, otherwise the row is
//     listed under "Problems in the trade log" (and still applied).
//     Players in a trade: a row with Player filled in (several players
//     comma-separated, "Jonathan Taylor, Tee Higgins") and Round and
//     Original Owner blank. It joins the trade with the same Year and
//     Order and only shows in the trade list; it doesn't touch the board.
//     A row with both a Round and players moves the pick and the players
//     the same way.
//
//   Draft Order (DRAFT_ORDER_CSV_URL):
//     Year, Slot, Manager — one row per slot. With an order, columns run
//     in draft-slot order with snake arrows on each round; without one
//     (e.g. 2027 before the order is set) columns are the current
//     managers in alphabetical order.
//
// Names must match the site's roster (data/manager_roster.json) exactly.
// Colors are per manager in MANAGER_COLORS, matching the league's draft
// sheet.

const TRADE_LOG_CSV_URL =
  "https://docs.google.com/spreadsheets/d/e/2PACX-1vR26n_XrpN9Y9v4OQWNeqNEdQ-hdQhIQEx6nLUD8Iq447J4X4Luj_3BcPi5DYcJlArCYdcRYqW77tar/pub?gid=1355501558&single=true&output=csv";
const DRAFT_ORDER_CSV_URL =
  "https://docs.google.com/spreadsheets/d/e/2PACX-1vR26n_XrpN9Y9v4OQWNeqNEdQ-hdQhIQEx6nLUD8Iq447J4X4Luj_3BcPi5DYcJlArCYdcRYqW77tar/pub?gid=1566104049&single=true&output=csv";
const ROSTER_URL = "data/manager_roster.json";
const STATS_URL = "data/stats.json";
const ROUNDS = 15;

// Matched to the colors in the league's draft-order sheet.
const MANAGER_COLORS = {
  "Josh Davis": "#4EA72E",
  "Daniel Bahamonde": "#FFC000",
  "Carl Bruce": "#44546A",
  "John Schauder": "#5B9BD5",
  "Brian Harris": "#D9D9D9",
  "Jay Nelson": "#F8CBAD",
  "Eddie McCumiskey": "#F08070",
  "Jason Carlton": "#BF9000",
  "Brian Kleinhenz": "#FF0000",
  "Kevin Mallon": "#7030A0",
  "Greg Wigton": "#C55A11",
  "Blake Pratt": "#FFFF99",
};
const FALLBACK_COLOR = "#BFBFBF";

// Short names as the league writes them ("Dan", "Brian H").
const SHORT_NAME_OVERRIDES = { "Daniel Bahamonde": "Dan" };

let roster = new Set();
let currentManagers = [];
let trades = [];       // normalized Trade Log pick rows
let playerMoves = [];  // normalized Trade Log player rows: {row, order, year, from, to, players}
let draftOrders = {};  // year -> [manager, ...] in slot order
let shortNames = {};

document.addEventListener("DOMContentLoaded", async () => {
  const wrap = document.getElementById("dp-wrap");
  let logText, orderText = "", stats;
  try {
    const [logRes, orderRes, rosterRes, statsRes] = await Promise.all([
      fetch(TRADE_LOG_CSV_URL),
      DRAFT_ORDER_CSV_URL ? fetch(DRAFT_ORDER_CSV_URL) : Promise.resolve(null),
      fetch(ROSTER_URL),
      fetch(STATS_URL),
    ]);
    if (!logRes.ok) throw new Error(`trade log HTTP ${logRes.status}`);
    if (orderRes && !orderRes.ok) throw new Error(`draft order HTTP ${orderRes.status}`);
    if (!rosterRes.ok) throw new Error(`roster HTTP ${rosterRes.status}`);
    logText = await logRes.text();
    if (orderRes) orderText = await orderRes.text();
    roster = new Set((await rosterRes.json()).managers || []);
    stats = statsRes.ok ? await statsRes.json() : {};
  } catch (err) {
    wrap.innerHTML = `<p class="load-state">Couldn't load the draft board sheets (${escapeHtml(err.message)}). ` +
      `If this keeps happening, check they're still Published to the web as CSV.</p>`;
    return;
  }

  currentManagers = ((stats.current_standings || {}).standings || []).map((r) => r.manager);
  shortNames = buildShortNames([...roster]);
  const problems = [];
  ({ picks: trades, players: playerMoves } = normalizeTrades(parseCsvRows(logText), problems));
  draftOrders = normalizeDraftOrder(parseCsvRows(orderText), problems);

  const years = [...new Set([...trades.map((t) => t.year), ...Object.keys(draftOrders).map(Number)])]
    .sort((a, b) => b - a);
  if (!years.length) {
    wrap.innerHTML = `<p class="load-state">No draft picks recorded yet.</p>`;
    return;
  }

  const select = document.getElementById("dp-year");
  select.innerHTML = years.map((y) => `<option value="${y}">${y}</option>`).join("");
  const wanted = Number(new URLSearchParams(location.search).get("year"));
  select.value = String(years.includes(wanted) ? wanted : years[0]);
  select.addEventListener("change", () => {
    const url = new URL(location.href);
    url.searchParams.set("year", select.value);
    history.replaceState(null, "", url);
    render(Number(select.value), problems);
  });
  render(Number(select.value), problems);
});

// --- Building one draft ---

function render(year, loadProblems) {
  document.getElementById("dp-title").textContent = `${year} Draft Board`;
  document.getElementById("dp-detail").textContent = "";

  const order = draftOrders[year] || null;
  const managers = order || [...new Set([...currentManagers,
    ...trades.filter((t) => t.year === year).map((t) => t.original)])].sort();
  document.getElementById("dp-note").textContent = order
    ? "Columns are in draft order; arrows show the snake."
    : "No draft order yet, so managers are listed alphabetically.";

  // Walk the log in Order, tracking each pick's holder and path.
  const problems = loadProblems.filter((p) => p.year === undefined || p.year === year).map((p) => p.text);
  const holder = {};   // "round|original" -> manager
  const path = {};     // "round|original" -> [manager, ...]
  const yearTrades = trades.filter((t) => t.year === year).sort((a, b) => a.order - b.order || a.row - b.row);
  for (const t of yearTrades) {
    const key = `${t.round}|${t.original}`;
    const was = holder[key] || t.original;
    if (t.from !== was) {
      problems.push(`Row ${t.row}: ${t.original}'s Round ${t.round} pick is listed as coming from ` +
        `${t.from}, but ${was} held it at that point.`);
    }
    if (t.from === t.to) {
      problems.push(`Row ${t.row}: From and To are both ${t.to}, so the pick doesn't move.`);
    }
    path[key] = (path[key] || [t.original]).concat(t.to);
    holder[key] = t.to;
  }

  const held = Object.fromEntries(managers.map((m) => [m, 0]));
  let rows = "";
  for (let round = 1; round <= ROUNDS; round++) {
    const reverse = order && round % 2 === 0;
    const arrow = order ? (reverse ? "&larr;" : "&rarr;") : "";
    let cells = "";
    for (const original of managers) {
      const key = `${round}|${original}`;
      const owner = holder[key] || original;
      held[owner] = (held[owner] || 0) + 1;
      const traded = owner !== original;
      const route = (path[key] || [original]).map((m) => shortNames[m] || m).join(" → ");
      const info = traded
        ? `${year} Round ${round}: ${shortNames[original] || original}'s pick, now ${shortNames[owner] || owner} (${route})`
        : `${year} Round ${round}: ${shortNames[original] || original}'s own pick`;
      cells += `<td class="dp-cell${traded ? " is-traded" : ""}" style="${colorStyle(owner)}"
                  title="${escapeHtml(info)}" data-info="${escapeHtml(info)}" tabindex="0">${escapeHtml(shortNames[owner] || owner)}</td>`;
    }
    rows += `<tr><th class="dp-round" scope="row">${round} ${arrow}</th>${cells}<th class="dp-round dp-round-end">${arrow} ${round}</th></tr>`;
  }

  const head = managers.map((m, i) =>
    `<th class="dp-head" style="${colorStyle(m)}" scope="col">${order ? `<span class="dp-slot">${i + 1}</span>` : ""}${escapeHtml(shortNames[m] || m)}</th>`).join("");
  const totals = managers.map((m) => `<td class="dp-total">${held[m] || 0}</td>`).join("");

  const wrap = document.getElementById("dp-wrap");
  wrap.innerHTML = `
    <table class="dp-table">
      <thead><tr><th class="dp-round dp-corner">Rd</th>${head}<th class="dp-round dp-corner">Rd</th></tr></thead>
      <tbody>${rows}</tbody>
      <tfoot><tr><th class="dp-round" scope="row">Picks</th>${totals}<th class="dp-round"></th></tr></tfoot>
    </table>`;
  wrap.querySelectorAll(".dp-cell").forEach((cell) => {
    cell.addEventListener("click", () => {
      document.getElementById("dp-detail").textContent = cell.dataset.info;
    });
  });

  renderTrades(year, yearTrades, playerMoves.filter((p) => p.year === year));
  const shown = groupRowProblems(problems);
  document.getElementById("dp-problems").innerHTML = shown.length
    ? `<h3 class="season-subhead">Problems in the trade log</h3><ul class="dp-problem-list">${
        shown.map((p) => `<li>${escapeHtml(p)}</li>`).join("")}</ul>`
    : "";
}

// "Trade 1: John gets Jay's 4th and Tee Higgins · Jay gets John's 6th"
function renderTrades(year, yearTrades, yearPlayers) {
  const groups = new Map();
  const add = (order) => {
    if (!groups.has(order)) groups.set(order, { picks: [], players: [] });
    return groups.get(order);
  };
  for (const t of yearTrades) add(t.order).picks.push(t);
  for (const p of yearPlayers) add(p.order).players.push(p);
  const el = document.getElementById("dp-trades");
  if (!groups.size) { el.innerHTML = ""; return; }
  const name = (m) => escapeHtml(shortNames[m] || m);
  // One clause per receiving manager, players first, then picks:
  // "John gets Tee Higgins, Greg's 7th and 14th".
  const items = [...[...groups.entries()].sort((a, b) => a[0] - b[0]).map(([, g]) => g)].map((group, i) => {
    const byTo = new Map();
    const slot = (to) => {
      if (!byTo.has(to)) byTo.set(to, { picks: [], players: [] });
      return byTo.get(to);
    };
    for (const t of group.picks) slot(t.to).picks.push(t);
    for (const p of group.players) slot(p.to).players.push(...p.players);
    const parts = [...byTo.entries()].map(([to, got]) => {
      // "Brian K's 5th and 6th", "John's 5th (via Brian K)"
      const bySource = new Map();
      for (const t of got.picks.sort((a, b) => a.round - b.round)) {
        const key = `${t.original}|${t.original === t.from ? "" : t.from}`;
        if (!bySource.has(key)) bySource.set(key, { t, rounds: [] });
        bySource.get(key).rounds.push(ordinal(t.round));
      }
      const pieces = got.players.map((pl) => escapeHtml(pl))
        .concat([...bySource.values()].map(({ t, rounds }) =>
          `${name(t.original)}'s ${joinAnd(rounds)}${t.original === t.from ? "" : ` (via ${name(t.from)})`}`));
      return `<b>${name(to)}</b> gets ${joinAnd(pieces)}`;
    });
    return `<li><span class="dp-trade-num">Trade ${i + 1}</span> ${parts.join(" · ")}</li>`;
  });
  el.innerHTML = `<h3 class="season-subhead">Trades</h3><ul class="dp-trade-list">${items.join("")}</ul>`;
}

// --- Sheet rows ---

function normalizeTrades(rows, problems) {
  const picks = [];
  const players = [];
  rows.forEach((r, idx) => {
    const row = idx + 2;  // header is row 1
    const playerList = (r["Player"] || r["Players"] || "").split(",").map((p) => p.trim()).filter(Boolean);
    const hasRound = (r["Round"] || "") !== "";
    if (!r["Order"] && !r["Year"] && !hasRound && !r["From"] && !r["To"] && !playerList.length) return;  // notes-only row
    const order = Number(r["Order"]), year = Number(r["Year"]), round = Number(r["Round"]);
    const original = r["Original Owner"] || "", from = r["From"] || "", to = r["To"] || "";
    if (!r["Order"] || Number.isNaN(order) || !year) {
      problems.push({ year: year || undefined, text: `Row ${row}: needs an Order and a Year — skipped.` });
      return;
    }
    if (hasRound && (!Number.isInteger(round) || round < 1 || round > ROUNDS)) {
      problems.push({ year, text: `Row ${row}: Round must be 1-${ROUNDS} — skipped.` });
      return;
    }
    if (!hasRound && !playerList.length) {
      problems.push({ year, text: `Row ${row}: needs a Round (for a pick) or a Player — skipped.` });
      return;
    }
    const names = hasRound ? [original, from, to] : [from, to];
    const unknown = names.filter((m) => !roster.has(m));
    if (unknown.length) {
      problems.push({ year, text: `Row ${row}: ${unknown.map((m) => `'${m}'`).join(", ")} isn't a manager name on the site — skipped.` });
      return;
    }
    if (hasRound) picks.push({ row, order, year, round, original, from, to });
    if (playerList.length) players.push({ row, order, year, from, to, players: playerList });
  });
  return { picks, players };
}

function normalizeDraftOrder(rows, problems) {
  const byYear = {};
  rows.forEach((r, idx) => {
    const year = Number(r["Year"]), slot = Number(r["Slot"]), mgr = r["Manager"] || "";
    if (!year || !slot) return;
    if (!roster.has(mgr)) {
      problems.push({ year, text: `Draft Order row ${idx + 2}: '${mgr}' isn't a manager name on the site — skipped.` });
      return;
    }
    (byYear[year] = byYear[year] || []).push({ slot, mgr });
  });
  const out = {};
  for (const [year, list] of Object.entries(byYear)) {
    out[year] = list.sort((a, b) => a.slot - b.slot).map((x) => x.mgr);
  }
  return out;
}

// --- CSV parsing (same minimal RFC4180 parser as parlay.js) ---

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
  const table = parseCsv(text || "");
  if (table.length === 0) return [];
  const headers = table[0].map((h) => h.trim());
  return table.slice(1)
    .filter((r) => r.some((cell) => cell.trim() !== ""))
    .map((r) => Object.fromEntries(headers.map((h, idx) => [h, (r[idx] ?? "").trim()])));
}

// --- Helpers ---

// "Row 14: needs a Year" ... "Row 49: needs a Year" -> "Rows 14-49: needs a
// Year". Rows with the same message are merged into runs of consecutive
// row numbers; other problems pass through unchanged.
function groupRowProblems(problems) {
  const byText = new Map();
  const out = [];
  for (const p of problems) {
    const m = /^Row (\d+): (.*)$/.exec(p);
    if (!m) { out.push(p); continue; }
    if (!byText.has(m[2])) { byText.set(m[2], []); out.push(m[2]); }
    byText.get(m[2]).push(Number(m[1]));
  }
  return out.map((p) => {
    const rows = byText.get(p);
    if (!rows) return p;
    const runs = [];
    for (const r of rows.sort((a, b) => a - b)) {
      const last = runs[runs.length - 1];
      if (last && r === last[1] + 1) last[1] = r; else runs.push([r, r]);
    }
    const label = runs.map(([a, b]) => (a === b ? `${a}` : `${a}–${b}`)).join(", ");
    return `${rows.length > 1 ? "Rows" : "Row"} ${label}: ${p}`;
  });
}

// First names, with the last initial added where two managers share one
// ("Brian H", "Brian K").
function buildShortNames(names) {
  const firstCount = {};
  names.forEach((n) => { const f = n.split(" ")[0]; firstCount[f] = (firstCount[f] || 0) + 1; });
  return Object.fromEntries(names.map((n) => {
    if (SHORT_NAME_OVERRIDES[n]) return [n, SHORT_NAME_OVERRIDES[n]];
    const [first, ...rest] = n.split(" ");
    return [n, firstCount[first] > 1 && rest.length ? `${first} ${rest[rest.length - 1][0]}` : first];
  }));
}

// Background in the manager's color, with black or white text, whichever
// reads better on it.
function colorStyle(manager) {
  const bg = MANAGER_COLORS[manager] || FALLBACK_COLOR;
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(bg.slice(i, i + 2), 16));
  const light = (0.299 * r + 0.587 * g + 0.114 * b) > 150;
  return `background:${bg};color:${light ? "#111" : "#fff"}`;
}

function joinAnd(items) {
  return items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

function ordinal(n) {
  const s = ["th", "st", "nd", "rd"], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
