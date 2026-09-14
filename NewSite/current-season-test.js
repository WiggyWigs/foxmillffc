// Current Season page — three sections (streaks, power rankings,
// standings), all reading from the same stats.json fetch. Power
// rankings and standings are fully precomputed in ingest_csv.py;
// streaks rendering does light client-side formatting only.

document.addEventListener("DOMContentLoaded", async () => {
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

  const seasonLabel = document.getElementById("season-year-label");
  const pageHeader = document.getElementById("page-season-header");
  const season = data.power_rankings?.season || data.current_streaks?.season
    || data.current_standings?.season;
  if (season && seasonLabel) {
    seasonLabel.textContent = `Fox Mill Fantasy Football Club — ${season} Season`;
  }
  if (season && pageHeader) {
    pageHeader.textContent = `${season} Season`;
  }

  // Each section renders independently — one section's bug should
  // never take down the rest of the page.
  const sections = [renderRecap, renderStreaks, renderStandings, renderPlayoffProbability, renderPowerRankings];
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
    prevHeading.textContent = `Week ${recap.previous_weekend_week} Impact Game`;
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

  const gotwWrap = document.getElementById("recap-gotw-wrap");
  if (recap.game_of_the_week) {
    gotwWrap.innerHTML = `<p class="recap-text">${recap.game_of_the_week}</p>`;
  } else {
    gotwWrap.innerHTML = `<p class="load-state">No preview yet — check back closer to kickoff.</p>`;
  }

  renderCallouts(recap.callouts || {});
}

function renderCallouts(callouts) {
  const section = document.getElementById("callouts-section");
  const grid = document.getElementById("callout-grid");

  const items = [];
  if (callouts.last_gotw_result) items.push(callouts.last_gotw_result);
  if (Array.isArray(callouts.new_records)) {
    callouts.new_records.forEach((item) => items.push(item));
  }
  if (callouts.longest_win_streak) items.push(callouts.longest_win_streak);
  if (callouts.longest_loss_streak) items.push(callouts.longest_loss_streak);
  if (callouts.biggest_margin) items.push(callouts.biggest_margin);
  if (callouts.lowest_scoring_team) items.push(callouts.lowest_scoring_team);
  if (callouts.highest_scoring_player) items.push(callouts.highest_scoring_player);

  if (items.length === 0) {
    section.style.display = "none";
    return;
  }

  section.style.display = "";
  grid.innerHTML = items.map(renderCalloutCard).join("");
}

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
      <td class="msi-score">${row.probability}%</td>
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
