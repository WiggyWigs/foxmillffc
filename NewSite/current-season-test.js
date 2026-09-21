// Current Season page — three sections (streaks, power rankings,
// standings), all reading from the same stats.json fetch. Power
// rankings and standings are fully precomputed in ingest_csv.py;
// streaks rendering does light client-side formatting only.

document.addEventListener("DOMContentLoaded", async () => {
  setupBoxScoreModal();
  setupStreakModal();
  setupHonorableMentionModal();
  setupHighestScoringPlayerModal();
  setupLowestScoringTeamModal();
  let data;
  try {
    const res = await fetch("data/stats_test.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    document.getElementById("streaks-wrap").innerHTML =
      `<p class="load-state">Couldn't load stats.json (${err.message}).</p>`;
    document.getElementById("power-wrap").innerHTML = "";
    document.getElementById("standings-wrap").innerHTML = "";
    return;
  }

  const pageHeader = document.getElementById("page-season-header");
  const season = data.power_rankings?.season || data.current_streaks?.season
    || data.current_standings?.season;
  if (season && pageHeader) {
    pageHeader.textContent = `${season} Season`;
  }

  // Each section renders independently — one section's bug should
  // never take down the rest of the page.
  const sections = [renderRecap, renderStandings, renderPlayoffProbability, renderPowerRankings, renderRecordBooks];
  for (const renderFn of sections) {
    try {
      renderFn(data);
    } catch (err) {
      console.error(`${renderFn.name} failed:`, err);
    }
  }
});

function renderRecap(data) {
  const recap = data.weekly_recap || {};

  const prevHeading = document.getElementById("recap-previous-heading");
  if (prevHeading && recap.previous_weekend_week != null) {
    prevHeading.textContent = `Week ${recap.previous_weekend_week} - Impact Game`;
  }

  const prevSubtitle = document.getElementById("recap-previous-subtitle");
  if (prevSubtitle && recap.previous_weekend_away_team && recap.previous_weekend_home_team) {
    prevSubtitle.textContent = `${recap.previous_weekend_away_team} vs ${recap.previous_weekend_home_team}`;
  }

  const prevWrap = document.getElementById("recap-previous-wrap");
  if (recap.previous_weekend) {
    prevWrap.innerHTML = `<p class="recap-text">${recap.previous_weekend}</p>`;
  } else {
    prevWrap.innerHTML = `<p class="load-state">No recap yet — check back after this week's games.</p>`;
  }

  const gotwHeading = document.getElementById("recap-gotw-heading");
  if (gotwHeading && recap.game_of_the_week_week != null) {
    gotwHeading.textContent = `Week ${recap.game_of_the_week_week} - Game of the Week`;
  }

  const gotwSubtitle = document.getElementById("recap-gotw-subtitle");
  if (gotwSubtitle && recap.game_of_the_week_away_team && recap.game_of_the_week_home_team) {
    gotwSubtitle.textContent = `${recap.game_of_the_week_away_team} vs ${recap.game_of_the_week_home_team}`;
  }

  const gotwWrap = document.getElementById("recap-gotw-wrap");
  if (recap.game_of_the_week) {
    gotwWrap.innerHTML = `<p class="recap-text">${recap.game_of_the_week}</p>`;
  } else {
    gotwWrap.innerHTML = `<p class="load-state">No preview yet — check back closer to kickoff.</p>`;
  }

  renderCallouts(recap.callouts || {}, data.current_highest_scoring_players, data.current_lowest_scoring_teams);
  renderBoxScores(recap.box_scores || []);
  renderHonorableMention(recap);
}

function renderHonorableMention(recap) {
  const wrap = document.getElementById("honorable-mention-wrap");
  if (!wrap) return;

  const hasData = recap.honorable_mention_away_team && recap.honorable_mention_home_team
    && recap.honorable_mention_away_score != null && recap.honorable_mention_home_score != null;
  if (!hasData) {
    wrap.style.display = "none";
    return;
  }
  wrap.style.display = "";

  document.getElementById("hm-away-team").textContent = recap.honorable_mention_away_team;
  document.getElementById("hm-away-manager").textContent = recap.honorable_mention_away_manager || "";
  document.getElementById("hm-away-score").textContent = recap.honorable_mention_away_score;
  document.getElementById("hm-home-team").textContent = recap.honorable_mention_home_team;
  document.getElementById("hm-home-manager").textContent = recap.honorable_mention_home_manager || "";
  document.getElementById("hm-home-score").textContent = recap.honorable_mention_home_score;

  const card = document.getElementById("honorable-mention-card");
  card.onclick = () => openHonorableMentionModal(recap);
}

function openHonorableMentionModal(recap) {
  const modal = document.getElementById("honorableMentionModal");
  const body = document.getElementById("honorableMentionModalBody");
  const closeBtn = document.getElementById("honorableMentionModalClose");
  if (!modal || !body) return;

  body.textContent = recap.honorable_mention || "No write-up available yet.";

  modal.classList.add("active");
  modal.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  if (closeBtn) closeBtn.focus();
}

function closeHonorableMentionModal() {
  const modal = document.getElementById("honorableMentionModal");
  if (!modal) return;
  modal.classList.remove("active");
  modal.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
}

function setupHonorableMentionModal() {
  const overlay = document.getElementById("honorableMentionModal");
  const closeBtn = document.getElementById("honorableMentionModalClose");
  if (!overlay || !closeBtn) return;

  closeBtn.addEventListener("click", closeHonorableMentionModal);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeHonorableMentionModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && overlay.classList.contains("active")) closeHonorableMentionModal();
  });
}

function renderBoxScores(boxScores) {
  const grid = document.getElementById("box-score-grid");
  if (!grid) return;

  if (boxScores.length === 0) {
    grid.innerHTML = `<p class="load-state">No box scores yet.</p>`;
    return;
  }

  grid.innerHTML = boxScores.map((b, i) => `
    <div class="box-score-card" data-box-score-index="${i}">
      <div class="box-score-winner">${b.winner_team} <span class="box-score-score">${b.winner_score}</span></div>
      <div class="box-score-loser">${b.loser_team} <span class="box-score-score">${b.loser_score}</span></div>
    </div>
  `).join("");

  grid.querySelectorAll("[data-box-score-index]").forEach((card) => {
    card.addEventListener("click", () => {
      const b = boxScores[parseInt(card.dataset.boxScoreIndex, 10)];
      openBoxScoreModal(b);
    });
  });
}

function openBoxScoreModal(boxScore) {
  const modal = document.getElementById("boxScoreModal");
  const title = document.getElementById("boxScoreModalTitle");
  const body = document.getElementById("boxScoreModalBody");
  const closeBtn = document.getElementById("boxScoreModalClose");
  if (!modal || !title || !body) return;

  title.textContent = `${boxScore.winner_team} ${boxScore.winner_score} - ${boxScore.loser_score} ${boxScore.loser_team}`;
  body.textContent = boxScore.narrative || "No write-up for this game yet.";
  modal.classList.add("active");
  modal.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  if (closeBtn) closeBtn.focus();
}

function closeBoxScoreModal() {
  const modal = document.getElementById("boxScoreModal");
  if (!modal) return;
  modal.classList.remove("active");
  modal.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
}

function setupBoxScoreModal() {
  const overlay = document.getElementById("boxScoreModal");
  const closeBtn = document.getElementById("boxScoreModalClose");
  if (!overlay || !closeBtn) return;

  closeBtn.addEventListener("click", closeBoxScoreModal);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeBoxScoreModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && overlay.classList.contains("active")) closeBoxScoreModal();
  });
}

function renderCallouts(callouts, highestScoringPlayers, lowestScoringTeams) {
  const section = document.getElementById("callouts-section");
  const grid = document.getElementById("callout-grid");

  // Each entry carries a "kind" so the four popup boxes (streaks,
  // lowest team, highest player) can share the Honorable Mention
  // format while sentence/record cards keep their existing look.
  const entries = [];
  if (callouts.last_gotw_result) entries.push({ item: callouts.last_gotw_result, kind: "sentence" });
  if (Array.isArray(callouts.new_records)) {
    callouts.new_records.forEach((item) => entries.push({ item, kind: "record" }));
  }
  if (callouts.longest_win_streak) entries.push({ item: callouts.longest_win_streak, kind: "streak" });
  if (callouts.longest_loss_streak) entries.push({ item: callouts.longest_loss_streak, kind: "streak" });
  if (callouts.lowest_scoring_team) entries.push({ item: callouts.lowest_scoring_team, kind: "lowest" });
  if (callouts.highest_scoring_player) entries.push({ item: callouts.highest_scoring_player, kind: "highest" });

  if (entries.length === 0) {
    section.style.display = "none";
    return;
  }

  section.style.display = "";
  grid.innerHTML = entries.map((e) =>
    ["streak", "lowest", "highest"].includes(e.kind)
      ? renderCalloutHmCard(e.item, e.kind)
      : renderCalloutCard(e.item)
  ).join("");

  equalizeCalloutHeights();
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(equalizeCalloutHeights);
  }

  const hasWeeklyScorers = highestScoringPlayers && Array.isArray(highestScoringPlayers.weeks)
    && highestScoringPlayers.weeks.length > 0;
  const hasWeeklyLowest = lowestScoringTeams && Array.isArray(lowestScoringTeams.weeks)
    && lowestScoringTeams.weeks.length > 0;

  Array.from(grid.children).forEach((el, i) => {
    const { item, kind } = entries[i];
    let onClick = null;
    if (kind === "streak" && item.streak_details) {
      onClick = () => openStreakModal(item);
    } else if (kind === "highest" && hasWeeklyScorers) {
      onClick = () => openHighestScoringPlayerModal(highestScoringPlayers);
    } else if (kind === "lowest" && hasWeeklyLowest) {
      onClick = () => openLowestScoringTeamModal(lowestScoringTeams);
    }
    if (onClick) {
      el.classList.add(el.classList.contains("callout-hm") ? "callout-hm-clickable" : "callout-clickable");
      el.addEventListener("click", onClick);
    }
  });
}

// Honorable Mention-style callout box: centered eyebrow label, name,
// optional italic subtitle, big number. Display wording is adjusted
// here (not in the generator) so the live page's data stays untouched.
function activeLabel(label) {
  return String(label || "").replace(/\bCurrent\b/g, "Active");
}

function renderCalloutHmCard(item, kind) {
  const valueDisplay = typeof item.value === "number"
    ? (Number.isInteger(item.value) ? item.value : item.value.toFixed(2))
    : item.value;

  let label = item.label;
  let headline = item.headline;
  let subtitle = item.subtitle || "";

  if (kind === "streak") {
    label = activeLabel(item.label);
    // Ties stack on separate lines instead of "A, B".
    const names = Array.isArray(item.streak_details) && item.streak_details.length
      ? item.streak_details.map((e) => e.manager)
      : String(item.headline).split(", ");
    headline = names.join("<br>");
  } else if (kind === "highest") {
    label = "Superstar";
    headline = item.headline;
    subtitle = "highest scoring player";
  }

  return `
    <div class="callout-hm">
      <span class="box-score-eyebrow">${label}</span>
      <div class="callout-hm-headline">${headline}</div>
      ${subtitle ? `<div class="callout-hm-subtitle">${subtitle}</div>` : ""}
      <div class="callout-hm-value">${valueDisplay}</div>
    </div>
  `;
}

// Every Honorable Mention-style box takes the height of the tallest one.
function equalizeCalloutHeights() {
  const cards = Array.from(document.querySelectorAll("#callout-grid .callout-hm"));
  if (cards.length === 0) return;
  cards.forEach((c) => { c.style.minHeight = ""; });
  const tallest = Math.max(...cards.map((c) => c.getBoundingClientRect().height));
  cards.forEach((c) => { c.style.minHeight = `${Math.ceil(tallest)}px`; });
}

window.addEventListener("resize", equalizeCalloutHeights);

function renderCalloutCard(item) {
  if (item.style === "sentence") {
    return `
      <div class="callout-item callout-sentence">
        <div class="callout-item-text">
          <span class="callout-label">${item.label}</span>
          <span class="callout-headline">${item.text}</span>
        </div>
      </div>
    `;
  }

  // Default: the name + big number "impact" card.
  const valueDisplay = typeof item.value === "number"
    ? (Number.isInteger(item.value) ? item.value : item.value.toFixed(2))
    : item.value;

  return `
    <div class="callout-item">
      <div class="callout-item-text">
        <span class="callout-label">${item.label}</span>
        <span class="callout-headline">${item.headline}</span>
        ${item.subtitle ? `<span class="callout-subtitle">${item.subtitle}</span>` : ""}
      </div>
      <div class="callout-value-wrap">
        <span class="callout-value">${valueDisplay}</span>
        ${item.unit ? `<span class="callout-unit">${item.unit}</span>` : ""}
      </div>
    </div>
  `;
}

// "Welcome to the Record Books" — plain narrative sentences, one per
// achievement, non-clickable and centered (matching the tone of the
// "last week's pick" callout elsewhere on this page rather than a
// table or card). Entries are grouped first by category, then by the
// exact stat value within that category — two managers who hit the
// SAME mark (e.g. tied game scores) become one "share the record"
// sentence together; two managers in the same category at different
// values still get their own separate sentences.
const RECORD_BOOKS_LABELS = {
  top_game_score: "Top 15 R/S Game Score",
  bottom_game_score: "Bottom 15 R/S Game Score",
  top_win_streak: "Top 5 R/S Winning Streak",
  top_loss_streak: "Top 5 R/S Losing Streak",
  "25th_win": "25th Career Victory",
  "25th_loss": "25th Career Defeat",
};

// Display order, top to bottom.
const RECORD_BOOKS_ORDER = [
  "top_game_score", "bottom_game_score",
  "top_win_streak", "top_loss_streak",
  "25th_win", "25th_loss",
];

function ordinal(n) {
  const suffixes = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (suffixes[(v - 20) % 10] || suffixes[v] || suffixes[0]);
}

function fmtRecordNumber(v) {
  return typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(2)) : v;
}

// Joins a list of already-HTML-safe name strings into natural
// English: "A", "A and B", or "A, B, and C".
function joinNames(names) {
  if (names.length === 1) return names[0];
  if (names.length === 2) return `${names[0]} and ${names[1]}`;
  return `${names.slice(0, -1).join(", ")}, and ${names[names.length - 1]}`;
}

// Builds the sentence for one tie-group: entries that share both a
// category (kind) and the exact same stat value. A group of one
// manager gets singular phrasing; two or more sharing the value get
// "share"/"tied for" phrasing instead.
function recordBooksSentence(kind, group) {
  const rank = ordinal(group[0].rank);
  const names = group.map((e) => `<b>${e.manager}</b>`);
  const value = group[0].value;
  const tied = group.length > 1;

  switch (kind) {
    case "top_game_score":
      return tied
        ? `${joinNames(names)} share the ${rank}-highest R/S game score in league history — ${fmtRecordNumber(value)} points.`
        : `${names[0]}'s ${fmtRecordNumber(value)} points is the ${rank}-highest R/S game score in league history.`;

    case "bottom_game_score":
      return tied
        ? `${joinNames(names)} share the ${rank}-lowest R/S game score in league history — ${fmtRecordNumber(value)} points.`
        : `${names[0]}'s ${fmtRecordNumber(value)} points is now the ${rank}-lowest R/S game score in league history.`;

    case "top_win_streak":
      return tied
        ? `${joinNames(names)} are tied for the ${rank}-longest R/S winning streak in league history, each at ${value} games.`
        : `${names[0]}'s active winning streak has reached ${value} games — the ${rank}-longest in league history.`;

    case "top_loss_streak":
      return tied
        ? `${joinNames(names)} are tied for the ${rank}-longest R/S losing streak in league history, each at ${value} games.`
        : `${names[0]}'s losing streak has reached ${value} games — the ${rank}-longest in league history.`;

    case "25th_win":
      return tied
        ? `${joinNames(names)} both just reached their 25th career win, tied for the ${rank}-fastest anyone has ever gotten there.`
        : `${names[0]} just picked up their 25th career win — the ${rank}-fastest anyone has ever reached that mark.`;

    case "25th_loss":
      return tied
        ? `${joinNames(names)} both just picked up their 25th career loss, tied for the ${rank}-fastest anyone has ever gotten there.`
        : `${names[0]} just picked up their 25th career loss — the ${rank}-fastest anyone has ever reached that mark.`;

    default:
      return "";
  }
}

function renderRecordBooks(data) {
  const divider = document.getElementById("record-books-divider");
  const section = document.getElementById("record-books-section");
  const wrap = document.getElementById("record-books-grid");
  if (!section || !wrap) return;

  const entries = data.weekly_recap?.record_books_entries || [];
  if (entries.length === 0) {
    section.style.display = "none";
    if (divider) divider.style.display = "none";
    wrap.innerHTML = "";
    return;
  }

  const byKind = {};
  entries.forEach((e) => {
    (byKind[e.kind] = byKind[e.kind] || []).push(e);
  });

  const items = [];
  RECORD_BOOKS_ORDER.forEach((kind) => {
    const kindEntries = byKind[kind];
    if (!kindEntries) return;

    const byValue = {};
    kindEntries.forEach((e) => {
      (byValue[String(e.value)] = byValue[String(e.value)] || []).push(e);
    });

    Object.values(byValue)
      .sort((a, b) => a[0].rank - b[0].rank)
      .forEach((group) => {
        items.push({ kind, sentence: recordBooksSentence(kind, group) });
      });
  });

  wrap.innerHTML = items.map((item) => `
    <div class="sentence-item">
      <span class="sentence-label sentence-label-lg">${RECORD_BOOKS_LABELS[item.kind]}</span>
      <p class="sentence-text">${item.sentence}</p>
    </div>
  `).join("");

  section.style.display = "";
  if (divider) divider.style.display = "";
}

function openStreakModal(item) {
  const modal = document.getElementById("streakModal");
  const badge = document.getElementById("streakModalBadge");
  const body = document.getElementById("streakModalBody");
  const closeBtn = document.getElementById("streakModalClose");
  if (!modal || !body) return;

  // Header once, then one block per manager: name, then their games.
  if (badge) badge.textContent = activeLabel(item.label);
  body.innerHTML = item.streak_details.map((entry) => {
    const gamesList = entry.games.map((g) => `
      <div class="streak-game-line">
        <span>vs ${g.opponent}: ${g.manager_score} - ${g.opponent_score}</span>
        <span class="streak-game-yearweek">(${g.year}, W${g.week})</span>
      </div>`).join("");
    return `
      <div class="streak-modal-block">
        <div class="modal-name">${entry.manager}</div>
        <div class="streak-modal-body">${gamesList}</div>
      </div>`;
  }).join("");

  modal.classList.add("active");
  modal.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  if (closeBtn) closeBtn.focus();
}

function closeStreakModal() {
  const modal = document.getElementById("streakModal");
  if (!modal) return;
  modal.classList.remove("active");
  modal.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
}

function setupStreakModal() {
  const overlay = document.getElementById("streakModal");
  const closeBtn = document.getElementById("streakModalClose");
  if (!overlay || !closeBtn) return;

  closeBtn.addEventListener("click", closeStreakModal);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeStreakModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && overlay.classList.contains("active")) closeStreakModal();
  });
}

function openHighestScoringPlayerModal(highestScoringPlayers) {
  const modal = document.getElementById("highestScoringPlayerModal");
  const body = document.getElementById("highestScoringPlayerModalBody");
  const closeBtn = document.getElementById("highestScoringPlayerModalClose");
  if (!modal || !body) return;

  const rows = (highestScoringPlayers.weeks || []).slice().sort((a, b) => a.week - b.week);

  body.innerHTML = `
    <table class="record-table highest-scoring-table">
      <thead>
        <tr>
          <th>Week</th>
          <th class="col-name">Manager</th>
          <th class="col-name">Player</th>
          <th>Points</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((r) => `
          <tr>
            <td>${r.week}</td>
            <td class="col-name">${r.manager}</td>
            <td class="col-name">${r.player}</td>
            <td>${r.points}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;

  modal.classList.add("active");
  modal.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  if (closeBtn) closeBtn.focus();
}

function closeHighestScoringPlayerModal() {
  const modal = document.getElementById("highestScoringPlayerModal");
  if (!modal) return;
  modal.classList.remove("active");
  modal.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
}

function setupHighestScoringPlayerModal() {
  const overlay = document.getElementById("highestScoringPlayerModal");
  const closeBtn = document.getElementById("highestScoringPlayerModalClose");
  if (!overlay || !closeBtn) return;

  closeBtn.addEventListener("click", closeHighestScoringPlayerModal);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeHighestScoringPlayerModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && overlay.classList.contains("active")) closeHighestScoringPlayerModal();
  });
}

function openLowestScoringTeamModal(lowestScoringTeams) {
  const modal = document.getElementById("lowestScoringTeamModal");
  const body = document.getElementById("lowestScoringTeamModalBody");
  const closeBtn = document.getElementById("lowestScoringTeamModalClose");
  if (!modal || !body) return;

  const rows = (lowestScoringTeams.weeks || []).slice().sort((a, b) => a.week - b.week);

  body.innerHTML = `
    <table class="record-table lowest-scoring-table">
      <thead>
        <tr>
          <th>Week</th>
          <th class="col-name">Manager</th>
          <th>Score</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((r) => `
          <tr>
            <td>${r.week}</td>
            <td class="col-name">${r.manager}</td>
            <td>${r.score}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;

  modal.classList.add("active");
  modal.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  if (closeBtn) closeBtn.focus();
}

function closeLowestScoringTeamModal() {
  const modal = document.getElementById("lowestScoringTeamModal");
  if (!modal) return;
  modal.classList.remove("active");
  modal.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
}

function setupLowestScoringTeamModal() {
  const overlay = document.getElementById("lowestScoringTeamModal");
  const closeBtn = document.getElementById("lowestScoringTeamModalClose");
  if (!overlay || !closeBtn) return;

  closeBtn.addEventListener("click", closeLowestScoringTeamModal);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeLowestScoringTeamModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && overlay.classList.contains("active")) closeLowestScoringTeamModal();
  });
}

function renderStreaks(data) {
  const wrap = document.getElementById("streaks-wrap");
  const cs = data.current_streaks;
  if (!cs) {
    wrap.innerHTML = `<p class="load-state">No streak data found yet.</p>`;
    return;
  }

  function streakTable(title, rows, key) {
    if (!rows || rows.length === 0) {
      return `<div class="record-section"><h3>${title}</h3><p class="load-state">No active streaks.</p></div>`;
    }
    const body = rows.map((row) => `
      <tr>
        <td class="col-name">${row.manager}</td>
        <td>${row[key]} games</td>
      </tr>
    `).join("");
    return `
      <div class="record-section">
        <h3>${title}</h3>
        <table class="record-table streak-table">
          <thead><tr><th class="col-name">Manager</th><th>Streak</th></tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    `;
  }

  const winTable = streakTable("Winning Streak Leaders", cs.top_current_winning_streaks, "win_streak");
  const loseTable = streakTable("Losing Streak Leaders", cs.top_current_losing_streaks, "loss_streak");

  wrap.innerHTML = `<div class="record-row">${winTable}${loseTable}</div>`;
}

function renderPlayoffProbability(data) {
  const section = document.getElementById("playoff-prob-wrap").closest(".record-section");
  const meta = document.getElementById("playoff-prob-meta");
  const wrap = document.getElementById("playoff-prob-wrap");
  const divider = section.previousElementSibling; // the <hr> right before this section

  const pp = data.playoff_probabilities;

  if (!pp || !pp.visible) {
    // Season not far enough along, or already fully decided — hide
    // the whole section (and its leading divider) rather than show
    // an empty box.
    if (pp && pp.reason === "too_early") {
      section.style.display = "";
      if (divider) divider.style.display = "";
      meta.textContent = "";
      wrap.innerHTML = `<p class="load-state">Coming after Week 3.</p>`;
    } else {
      section.style.display = "none";
      if (divider) divider.style.display = "none";
    }
    return;
  }

  section.style.display = "";
  if (divider) divider.style.display = "";
  const seasonCount = data.playoff_probability_model?.seasons_used?.length || 0;
  meta.textContent = `Based on ${seasonCount} historical season${seasonCount === 1 ? "" : "s"} through Week ${pp.current_week}, adjusted for points scored and schedule difficulty.`;

  const rows = pp.managers; // already sorted by probability descending

  const body = rows.map((row) => `
    <tr>
      <td class="col-name">${row.manager}</td>
      <td>${row.wins}-${row.losses}</td>
      <td class="msi-score">${row.clinched ? "<strong>Clinched</strong>" : (row.eliminated ? "Eliminated" : `${row.probability}%`)}</td>
      <td class="num col-extra">${row.points_scored.toFixed(1)}</td>
      <td class="num col-extra">${row.schedule_difficulty >= 0 ? "+" : ""}${(row.schedule_difficulty * 100).toFixed(1)}%</td>
    </tr>
  `).join("");

  wrap.innerHTML = `
    <table class="msi-table">
      <thead>
        <tr>
          <th class="col-name">Manager</th>
          <th>Record</th>
          <th class="col-msi">Probability</th>
          <th class="num col-extra">Points</th>
          <th class="num col-extra">Sched Diff</th>
        </tr>
      </thead>
      <tbody>${body}</tbody>
    </table>
  `;
}

function renderPowerRankings(data) {
  const wrap = document.getElementById("power-wrap");
  const pr = data.power_rankings;
  if (!pr || !pr.rankings || pr.rankings.length === 0) {
    wrap.innerHTML = `<p class="load-state">No power rankings data found yet.</p>`;
    return;
  }

  const rows = pr.rankings; // already sorted by power_score descending

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
          <th class="col-rank">Rank</th>
          <th class="col-name">Manager</th>
          <th class="col-msi">Tot Points</th>
          <th class="num col-extra">Win %</th>
          <th class="num col-extra">Scoring</th>
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
          <td class="num col-extra">${row.win_pct_points}</td>
          <td class="num col-extra">${row.points_scored_points}</td>
          <td class="num col-extra">${row.schedule_difficulty_points}</td>
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

function renderStandings(data) {
  const wrap = document.getElementById("standings-wrap");
  const st = data.current_standings;
  if (!st || !st.standings || st.standings.length === 0) {
    wrap.innerHTML = `<p class="load-state">No standings data found yet.</p>`;
    return;
  }

  const rows = st.standings; // already sorted with H2H/points tiebreak applied

  const body = rows.map((row) => {
    const record = row.ties > 0 ? `${row.wins}-${row.losses}-${row.ties}` : `${row.wins}-${row.losses}`;
    return `
      <tr>
        <td class="col-name">${row.manager}</td>
        <td class="col-name">${row.team_name}</td>
        <td>${record}</td>
        <td>${row.points_for.toFixed(2)}</td>
        <td>${row.points_against.toFixed(2)}</td>
      </tr>
    `;
  }).join("");

  wrap.innerHTML = `
    <table class="record-table standings-table">
      <thead>
        <tr>
          <th class="col-name">Manager</th>
          <th class="col-name">Team Name</th>
          <th>Record</th>
          <th>Points For</th>
          <th>Points Against</th>
        </tr>
      </thead>
      <tbody>${body}</tbody>
    </table>
  `;
}
