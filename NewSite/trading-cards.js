// Trading Cards page — one trading card per manager, with the standings
// stamp and earned badges layered on top. Everything comes precomputed
// from stats.json's "player_cards" (scripts/player_cards.py); this file
// only lays it out. Add ?season=2026 to the URL to show a past season.
//
// Images:
//   images/cards/<first>-<last>-<year>.jpg   e.g. daniel-bahamonde-2026.jpg
//   images/badges/<badge-file>.png           see BADGES in badges.js
//   images/badges/rank-01.png … rank-12.png  standings stamps
// A missing card falls back to images/cards/template.jpg (the blank card)
// with the manager's name and season printed into its banners. A
// missing badge keeps its space and shows its initials.

const CARD_PLACEHOLDER = "images/cards/template.jpg";
const BADGE_PLACEHOLDER = "images/badges/badge-placeholder.png";

// Badges are clicked straight off the card only where there's a mouse.
// On touch screens they're too small to hit, so a tap anywhere on the
// card opens the pop-up instead.
const canClickBadges = window.matchMedia("(hover: hover) and (pointer: fine)").matches;

let season = null;
let allGames = [];   // stats.json game log, for the back of the card

document.addEventListener("DOMContentLoaded", async () => {
  setupModal();
  setupBadgeToggle();
  const grid = document.getElementById("pc-grid");
  let data;
  try {
    const res = await fetch("data/stats.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
    allGames = data.games || [];
  } catch (err) {
    grid.innerHTML = `<p class="load-state">Couldn't load stats.json (${escapeHtml(err.message)}).</p>`;
    return;
  }

  const pc = data.player_cards;
  const wanted = new URLSearchParams(location.search).get("season");
  season = pc?.seasons?.[wanted || pc?.current_season];
  if (!season) {
    grid.innerHTML = `<p class="load-state">No trading cards yet.</p>`;
    return;
  }

  document.getElementById("pc-title").textContent = `${season.season} Trading Cards`;
  const through = season.regular_season_complete
    ? "Final regular-season cards."
    : `Through Week ${season.through_week}.`;
  document.getElementById("pc-meta").textContent =
    `${through} ${canClickBadges ? "Click a card or a badge" : "Tap a card"} to see the badges.`;

  grid.innerHTML = season.cards.map((card, i) =>
    `<button type="button" class="pc-card-btn" data-index="${i}"
       aria-label="${escapeHtml(card.manager)}, ${ordinal(card.rank)} place, ${badgeCountLabel(card)}">
       ${cardHtml(card)}
     </button>`
  ).join("");

  grid.addEventListener("click", (e) => {
    const btn = e.target.closest(".pc-card-btn");
    if (!btn) return;
    const badgeEl = canClickBadges ? e.target.closest("[data-badge]") : null;
    openModal(season.cards[Number(btn.dataset.index)], badgeEl?.dataset.badge || null);
  });
});

// "Show badges" checkbox: hides the badge icons layered on the cards
// (grid and pop-up) by toggling a class on <body>. The standings stamp
// and the pop-up's badge list stay. The choice is remembered per browser.
const SHOW_BADGES_KEY = "pc-show-badges";

function setupBadgeToggle() {
  const box = document.getElementById("pc-show-badges");
  let saved = null;
  try { saved = localStorage.getItem(SHOW_BADGES_KEY); } catch {}
  box.checked = saved !== "false";
  const apply = () => {
    document.body.classList.toggle("pc-hide-badges", !box.checked);
    try { localStorage.setItem(SHOW_BADGES_KEY, String(box.checked)); } catch {}
  };
  box.addEventListener("change", apply);
  apply();
}

// --- Card markup (used for the grid and the larger copy in the pop-up) ---

// lazy: true for the grid. The pop-up copy loads straight away, because
// iPhone Safari can fail to start a lazy image inside a scrolling pop-up.
function cardHtml(card, lazy = true) {
  const src = `images/cards/${card.slug}-${season.season}.jpg`;
  const badges = card.badges.map((b) => badgeHtml(b, "pc-badge")).join("");
  return `
    <div class="pc-card">
      <img class="pc-card-img" src="${src}" alt=""${lazy ? ' loading="lazy"' : ""}
           onerror="cardImageMissing(this)">
      <div class="pc-placeholder-name" style="font-size:${placeholderNameSize(card.manager)}cqw">${escapeHtml(card.manager)}</div>
      <div class="pc-placeholder-year">${season.season}</div>
      <div class="pc-stamp">${stampHtml(card)}</div>
      <div class="pc-badges">${badges}</div>
    </div>`;
}

// The stamp is meant to look hand-pressed: each card gets its own tilt
// (up to 5 degrees either way) and a small nudge off centre. It comes
// from a hash of the manager, season and rank rather than Math.random(),
// so a stamp sits the same way on every visit and in the pop-up, and
// only moves when the rank changes.
function stampHtml(card) {
  const rank = card.rank;
  const n = season.managers_in_league;
  const file = `images/badges/rank-${String(rank).padStart(2, "0")}.png`;
  const h = hashString(`${card.slug}-${season.season}-${rank}`);
  const tilt = ((h % 1001) / 1000 * 10 - 5).toFixed(1);
  const dx = ((h >>> 10) % 13) - 6;
  const dy = ((h >>> 20) % 13) - 6;
  const style = `transform: translate(${dx}%, ${dy}%) rotate(${tilt}deg)`;
  return `<img src="${file}" alt="${rank} of ${n}" style="${style}" onerror="stampImageMissing(this)">
          <span class="pc-stamp-text" style="${style}">${rank}/${n}</span>`;
}

function hashString(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function badgeHtml(badge, cls) {
  const meta = BADGES[badge.id];
  if (!meta) return "";
  const number = meta.numbered && badge.count != null
    ? `<span class="pc-badge-num${meta.numberStyle === "light" ? " is-light" : ""}"${meta.numberTop ? ` style="top:${meta.numberTop}"` : ""}>${badge.count}</span>`
    : "";
  return `
    <span class="${cls}" data-badge="${badge.id}" title="${escapeHtml(meta.name)}">
      <img src="images/badges/${meta.file}" alt="${escapeHtml(meta.name)}"
           onerror="badgeImageMissing(this)">
      ${number}
      <span class="pc-badge-initials">${meta.initials || initials(meta.name)}</span>
    </span>`;
}

// Fallbacks for artwork that hasn't been added yet.
function cardImageMissing(img) {
  img.onerror = null;
  img.src = CARD_PLACEHOLDER;
  img.closest(".pc-card").classList.add("is-placeholder");
}
function stampImageMissing(img) {
  img.onerror = null;
  img.closest(".pc-stamp").classList.add("is-placeholder");
}
function badgeImageMissing(img) {
  img.parentElement.classList.add("is-placeholder");
  if (img.src.endsWith(BADGE_PLACEHOLDER)) {
    // No stand-in image either: keep the space, show just the initials.
    img.onerror = null;
    img.style.visibility = "hidden";
    return;
  }
  img.src = BADGE_PLACEHOLDER;
}

// --- Back of the card (pop-up only) ---
//
// images/cards/back-<rank>-<year>.jpg (or the shared back-<year>.jpg) is
// the blank back; the manager's name goes
// in its red header and the season's numbers in the cream body, worked
// out here from the game log so they change every week. Summary lines
// are regular season only (same as the standings); the game list also
// includes playoff games once there are any.

function backHtml(card) {
  const yr = Number(season.season);
  const mine = allGames
    .filter((g) => g.year === yr && (g.away_manager === card.manager || g.home_manager === card.manager))
    .sort((a, b) => weekOrder(a.week) - weekOrder(b.week));
  const rows = mine.map((g) => {
    const away = g.away_manager === card.manager;
    const own = away ? g.away_score : g.home_score;
    const opp = away ? g.home_score : g.away_score;
    const result = g.tie ? "T" : g.winner === card.manager ? "W" : "L";
    return { regular: g.game_type === "Regular", week: g.week, oppTeam: away ? g.home_team : g.away_team,
             own, opp, result, gameType: g.game_type };
  });
  const reg = rows.filter((r) => r.regular);
  const w = reg.filter((r) => r.result === "W").length;
  const l = reg.filter((r) => r.result === "L").length;
  const t = reg.filter((r) => r.result === "T").length;
  const pf = reg.reduce((sum, r) => sum + r.own, 0);
  const pa = reg.reduce((sum, r) => sum + r.opp, 0);
  const streak = (res) => {
    let best = 0, run = 0;
    for (const r of reg) { run = r.result === res ? run + 1 : 0; best = Math.max(best, run); }
    return best;
  };

  // Two per row: Record | Average Score, Points For | Points Against,
  // Winning Streak | Losing Streak (the longest of each this season).
  const stats = [
    ["Record", t ? `${w}-${l}-${t}` : `${w}-${l}`],
    ["Average Score", reg.length ? (pf / reg.length).toFixed(2) : "—"],
    ["Points For", pf.toFixed(2)],
    ["Points Against", pa.toFixed(2)],
    ["Winning Streak", String(streak("W"))],
    ["Losing Streak", String(streak("L"))],
  ].map(([k, v]) => `<div class="pc-back-stat"><span>${k}</span><span>${escapeHtml(v)}</span></div>`).join("");

  const games = rows.map((r) => {
    const label = r.regular ? "" : ` (${escapeHtml(r.gameType)})`;
    return `<div class="pc-back-game">
        <span class="pc-back-game-name">vs. ${escapeHtml(r.oppTeam)}${label}:</span>
        <span class="pc-back-game-score">${r.own.toFixed(2)} - ${r.opp.toFixed(2)}</span>
        <span class="pc-back-game-result is-${r.result}">${r.result}</span>
      </div>`;
  }).join("");

  return `
    <div class="pc-back">
      <img class="pc-back-img" src="images/cards/back-${String(card.rank).padStart(2, "0")}-${season.season}.jpg" alt=""
           data-fallback="images/cards/back-${season.season}.jpg" onerror="backImageMissing(this)">
      <div class="pc-back-name" style="font-size:${backNameSize(card.manager)}cqw">${escapeHtml(card.manager)}</div>
      <div class="pc-back-body">
        <div class="pc-back-stats">${stats}</div>
        <hr class="pc-back-rule">
        <div class="pc-back-games" style="font-size:${backGameFontSize(rows.length)}cqw">${games || '<div class="pc-back-game">No games yet.</div>'}</div>
      </div>
    </div>`;
}

// The back's name area is 68.5% of the card wide; long names shrink to
// stay on one line (same idea as placeholderNameSize on the front).
function backNameSize(name) {
  return Math.min(8, 66 / (name.length * 0.56)).toFixed(2);
}

// With the stats two per row, the game list has about 80% of the card's
// width in height (cqw units, line-height 1.32): a full 17-game playoff
// season fits at full size, and anything longer shrinks to fit.
function backGameFontSize(n) {
  return Math.min(3.3, 80 / (Math.max(n, 1) * 1.32)).toFixed(2);
}

// Backs follow the standings: rank 1 gets back-01-<year>.jpg, rank 12
// back-12-<year>.jpg. Until those exist, every card uses the shared
// back-<year>.jpg; with neither, the back is plain cream.
function backImageMissing(img) {
  const fallback = img.dataset.fallback;
  if (fallback && !img.src.endsWith(fallback)) {
    img.src = fallback;
    return;
  }
  img.onerror = null;
  img.style.visibility = "hidden";
}

function weekOrder(week) {
  const w = String(week);
  return w.startsWith("P") ? 100 + Number(w.slice(1)) : Number(w);
}

function flipCardHtml(card) {
  return `
    <button type="button" class="pc-flip" aria-label="Flip card" aria-pressed="false">
      <div class="pc-flip-face pc-flip-front">${cardHtml(card, false)}</div>
      <div class="pc-flip-face pc-flip-back" hidden>${backHtml(card)}</div>
    </button>
    <div class="pc-flip-hint">Tap the card to flip it</div>`;
}

// The flip keeps turning one way, like a real card: 0 -> 90 degrees
// (edge-on, neither face visible), swap faces, then -90 -> 0. Each half
// is its own short animation with nothing held afterwards, so the card
// is never left rotated, which keeps clear of the iPhone Safari repaint
// bug (see #pcModal in styles.css). Each tap flips the same direction,
// as if turning the card over in your hand. Reduced-motion users get an
// instant swap.
const FLIP_HALF_MS = 450;   // 0.9s for the whole flip

function setupFlip(wrap) {
  const btn = wrap.querySelector(".pc-flip");
  const front = wrap.querySelector(".pc-flip-front");
  const back = wrap.querySelector(".pc-flip-back");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let busy = false;
  const swap = () => {
    const showBack = back.hidden;
    back.hidden = !showBack;
    front.hidden = showBack;
    btn.setAttribute("aria-pressed", String(showBack));
  };
  const turn = (from, to, easing) => btn.animate(
    [{ transform: `perspective(1200px) rotateY(${from}deg)` },
     { transform: `perspective(1200px) rotateY(${to}deg)` }],
    { duration: FLIP_HALF_MS, easing },
  ).finished;

  btn.addEventListener("click", async () => {
    if (busy) return;
    if (reduce || !btn.animate) { swap(); return; }
    busy = true;
    try {
      await turn(0, 90, "cubic-bezier(0.4, 0, 1, 1)");    // speed up into edge-on
      swap();
      await turn(-90, 0, "cubic-bezier(0, 0, 0.2, 1)");   // ease out as it lands
    } finally {
      busy = false;
    }
  });
}

// --- Pop-up ---

function openModal(card, focusBadgeId) {
  const modal = document.getElementById("pcModal");
  document.getElementById("pcModalBadge").textContent = `${season.season} Trading Card`;
  document.getElementById("pcModalName").textContent = card.manager;
  const record = card.ties > 0 ? `${card.wins}-${card.losses}-${card.ties}` : `${card.wins}-${card.losses}`;
  document.getElementById("pcModalMeta").textContent =
    `${card.team_name} · ${ordinal(card.rank)} place · ${record} · ${card.points_for.toFixed(2)} points`;
  document.getElementById("pcModalCard").innerHTML = flipCardHtml(card);
  setupFlip(document.getElementById("pcModalCard"));

  const list = document.getElementById("pcModalBadges");
  list.innerHTML = card.badges.length
    ? card.badges.map((b) => badgeDetailHtml(b, b.id === focusBadgeId)).join("")
    : `<p class="pc-no-badges">No badges yet.</p>`;

  modal.classList.add("active");
  modal.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  document.getElementById("pcModalClose").focus();

  const focused = list.querySelector(".pc-detail.is-focus");
  if (focused) focused.scrollIntoView({ block: "nearest" });
}

function closeModal() {
  const modal = document.getElementById("pcModal");
  modal.classList.remove("active");
  modal.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
}

function setupModal() {
  const overlay = document.getElementById("pcModal");
  document.getElementById("pcModalClose").addEventListener("click", closeModal);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && overlay.classList.contains("active")) closeModal();
  });
}

function badgeDetailHtml(badge, isFocus) {
  const meta = BADGES[badge.id];
  if (!meta) return "";
  const title = meta.numbered && badge.count != null ? `${meta.name} ×${badge.count}` : meta.name;
  const lines = badgeEventLines(badge).map((l) => `<li>${l}</li>`).join("");
  return `
    <div class="pc-detail${isFocus ? " is-focus" : ""}">
      ${badgeHtml(badge, "pc-detail-badge")}
      <div class="pc-detail-text">
        <div class="pc-detail-name">${escapeHtml(title)}</div>
        <div class="pc-detail-rule">${escapeHtml(meta.rule)}</div>
        <ul class="pc-detail-events">${lines}</ul>
      </div>
    </div>`;
}

// --- Helpers ---

// The template's name banner is 48% of the card wide. Big Shoulders
// capitals average a little over half an em, so long names shrink to fit.
function placeholderNameSize(name) {
  return Math.min(7.2, 48 / (name.length * 0.58)).toFixed(2);
}

function badgeCountLabel(card) {
  const n = card.badges.length;
  return n === 1 ? "1 badge" : `${n} badges`;
}

function initials(name) {
  return name.replace(/^The /, "").split(/\s+/).map((w) => w[0]).join("").slice(0, 2);
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
