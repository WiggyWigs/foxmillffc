// Player Cards page — one trading card per manager, with the standings
// stamp and earned badges layered on top. Everything comes precomputed
// from stats.json's "player_cards" (scripts/player_cards.py); this file
// only lays it out. Add ?season=2026 to the URL to show a past season.
//
// Images:
//   images/cards/<first>-<last>-<year>.jpg   e.g. daniel-bahamonde-2026.jpg
//   images/badges/<badge-file>.png           see BADGES below
//   images/badges/rank-01.png … rank-12.png  standings stamps
// A missing image falls back to a placeholder, so a card or badge can
// go live before its artwork is finished.

const BADGES = {
  longest_win_streak: {
    name: "Longest Win Streak", file: "longest-win-streak.png", numbered: true,
    // Earned with the first win, but a "1" on the badge reads as a
    // knock, so the number only shows from a 2-game streak.
    minNumber: 2,
    rule: "This manager's longest run of straight wins this season.",
  },
  weekly_high_score: {
    name: "Weekly High Score", file: "weekly-high-score.png", numbered: true,
    rule: "Weeks with the league's highest score.",
  },
  superstar: {
    name: "Superstar", file: "superstar.png", numbered: true,
    rule: "Weeks with the league's highest-scoring starter.",
  },
  giant_killer: {
    name: "Giant Killer", file: "giant-killer.png", numbered: false,
    rule: "Week 5 or later: beat a top-5 team ranked at least 5 spots higher going into the week.",
  },
  high_point_club: {
    name: "High Point Club", file: "high-point-club.png", numbered: false,
    rule: "Scored 150 or more points in a game.",
  },
  the_punisher: {
    name: "The Punisher", file: "the-punisher.png", numbered: false,
    rule: "Won a game by more than 50 points.",
  },
  ice_cold: {
    name: "Ice Cold", file: "ice-cold.png", numbered: false,
    rule: "Lost 5 games in a row.",
  },
  businessman: {
    name: "Businessman", file: "businessman.png", numbered: false,
    rule: "Most transactions (adds, drops and trades) in the regular season.",
  },
};

const CARD_PLACEHOLDER = "images/cards/card-placeholder.jpg";
const BADGE_PLACEHOLDER = "images/badges/badge-placeholder.png";

// Badges are clicked straight off the card only where there's a mouse.
// On touch screens they're too small to hit, so a tap anywhere on the
// card opens the pop-up instead.
const canClickBadges = window.matchMedia("(hover: hover) and (pointer: fine)").matches;

let season = null;

document.addEventListener("DOMContentLoaded", async () => {
  setupModal();
  const grid = document.getElementById("pc-grid");
  let data;
  try {
    const res = await fetch("data/stats.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    grid.innerHTML = `<p class="load-state">Couldn't load stats.json (${escapeHtml(err.message)}).</p>`;
    return;
  }

  const pc = data.player_cards;
  const wanted = new URLSearchParams(location.search).get("season");
  season = pc?.seasons?.[wanted || pc?.current_season];
  if (!season) {
    grid.innerHTML = `<p class="load-state">No player cards yet.</p>`;
    return;
  }

  document.getElementById("pc-title").textContent = `${season.season} Player Cards`;
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

// --- Card markup (used for the grid and the larger copy in the pop-up) ---

function cardHtml(card) {
  const src = `images/cards/${card.slug}-${season.season}.jpg`;
  const badges = card.badges.map((b) => badgeHtml(b, "pc-badge")).join("");
  return `
    <div class="pc-card">
      <img class="pc-card-img" src="${src}" alt="" loading="lazy"
           onerror="cardImageMissing(this)">
      <div class="pc-placeholder-name">${escapeHtml(card.manager)}</div>
      <div class="pc-stamp">${stampHtml(card.rank)}</div>
      <div class="pc-badges">${badges}</div>
    </div>`;
}

function stampHtml(rank) {
  const n = season.managers_in_league;
  const file = `images/badges/rank-${String(rank).padStart(2, "0")}.png`;
  return `<img src="${file}" alt="${rank} of ${n}" onerror="stampImageMissing(this)">
          <span class="pc-stamp-text">${rank}/${n}</span>`;
}

function badgeHtml(badge, cls) {
  const meta = BADGES[badge.id];
  if (!meta) return "";
  const number = showsNumber(meta, badge)
    ? `<span class="pc-badge-num">${badge.count}</span>` : "";
  return `
    <span class="${cls}" data-badge="${badge.id}" title="${escapeHtml(meta.name)}">
      <img src="images/badges/${meta.file}" alt="${escapeHtml(meta.name)}"
           onerror="badgeImageMissing(this)">
      ${number}
      <span class="pc-badge-initials">${initials(meta.name)}</span>
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
  img.onerror = null;
  img.src = BADGE_PLACEHOLDER;
  img.parentElement.classList.add("is-placeholder");
}

// --- Pop-up ---

function openModal(card, focusBadgeId) {
  const modal = document.getElementById("pcModal");
  document.getElementById("pcModalBadge").textContent = `${season.season} Player Card`;
  document.getElementById("pcModalName").textContent = card.manager;
  const record = card.ties > 0 ? `${card.wins}-${card.losses}-${card.ties}` : `${card.wins}-${card.losses}`;
  document.getElementById("pcModalMeta").textContent =
    `${card.team_name} · ${ordinal(card.rank)} place · ${record} · ${card.points_for.toFixed(2)} points`;
  document.getElementById("pcModalCard").innerHTML = cardHtml(card);

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
  const title = showsNumber(meta, badge) ? `${meta.name} ×${badge.count}` : meta.name;
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

function badgeEventLines(badge) {
  const ev = badge.events || [];
  const score = (e) => `${e.manager_score.toFixed(2)}–${e.opponent_score.toFixed(2)}`;
  const opp = (e) => escapeHtml(e.opponent);
  switch (badge.id) {
    case "longest_win_streak": {
      const first = ev[0]?.week, last = ev[ev.length - 1]?.week;
      const games = ev.map((e) => `Week ${e.week}: beat ${opp(e)} ${score(e)}`);
      return ev.length === 1 ? games : [`${ev.length} straight wins, Weeks ${first}–${last}`].concat(games);
    }
    case "weekly_high_score":
      return ev.map((e) => `Week ${e.week}: ${e.manager_score.toFixed(2)} points`);
    case "superstar":
      return ev.map((e) => `Week ${e.week}: ${escapeHtml(e.player)} (${escapeHtml(e.position)}), ${e.points} points`);
    case "giant_killer":
      return ev.map((e) => `Week ${e.week}: ranked ${ordinal(e.manager_rank)}, beat ${ordinal(e.opponent_rank)}-place ${opp(e)} ${score(e)}`);
    case "high_point_club":
      return ev.map((e) => `Week ${e.week}: ${e.manager_score.toFixed(2)} points vs ${opp(e)}`);
    case "the_punisher":
      return ev.map((e) => `Week ${e.week}: beat ${opp(e)} by ${e.margin.toFixed(2)} (${score(e)})`);
    case "ice_cold":
      return ev.map((e) => `${e.length} straight losses, Weeks ${e.start_week}–${e.end_week}`);
    default:
      return [];
  }
}

// --- Helpers ---

function showsNumber(meta, badge) {
  return meta.numbered && badge.count != null && badge.count >= (meta.minNumber || 1);
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
