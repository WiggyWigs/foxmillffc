// Hall of Champions — unlike the golf site's hardcoded CHAMPIONS object,
// every number here is derived live from stats.json each page load.
// Nothing is typed in manually, so it can never drift out of sync with
// the actual game log.

async function loadChampions() {
  let data;
  try {
    const res = await fetch("data/stats.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    console.error("Couldn't load stats.json:", err.message);
    return;
  }

  const YEARS = ["2025", "2024", "2023"];
  const champions = {};

  YEARS.forEach((year) => {
    const entry = Object.entries(data.managers).find(
      ([, m]) => m.seasons[year] && m.seasons[year].champion === true
    );
    if (!entry) {
      console.warn(`No champion found for ${year} in stats.json`);
      return;
    }
    const [name, m] = entry;
    const s = m.seasons[year];

    const regGames = s.regular_wins + s.regular_losses + s.regular_ties;
    const avgScore = regGames ? (s.points_for_regular / regGames).toFixed(1) : "—";

    const totalWins = s.regular_wins + s.playoff_wins;
    const totalLosses = s.regular_losses + s.playoff_losses;
    const totalTies = s.regular_ties + s.playoff_ties;
    const record = totalTies > 0
      ? `${totalWins}-${totalLosses}-${totalTies}`
      : `${totalWins}-${totalLosses}`;

    // Championship Game data: pulled from the raw game log, using TEAM
    // names (not manager names), split into structured fields so the
    // template can lay out winner/vs/loser as separate elements rather
    // than one combined text string.
    const champGame = data.games.find(
      (g) => g.year.toString() === year && g.game_type === "Championship"
    );
    let champGameData = null;
    if (champGame) {
      if (champGame.tie) {
        champGameData = {
          winTeam: champGame.away_team, winScore: champGame.away_score,
          loseTeam: champGame.home_team, loseScore: champGame.home_score,
          isTie: true,
        };
      } else {
        const winnerIsAway = champGame.winner === champGame.away_manager;
        champGameData = {
          winTeam: winnerIsAway ? champGame.away_team : champGame.home_team,
          winScore: Math.max(champGame.away_score, champGame.home_score),
          loseTeam: winnerIsAway ? champGame.home_team : champGame.away_team,
          loseScore: Math.min(champGame.away_score, champGame.home_score),
          isTie: false,
        };
      }
    }

    champions[year] = {
      name,
      avg: avgScore,
      record,
      champGame: champGameData,
    };
  });

  // Fill in portrait alt text now that we know each year's actual champion.
  document.querySelectorAll(".portrait-frame").forEach((btn) => {
    const year = btn.getAttribute("data-year");
    const c = champions[year];
    if (c) {
      const img = btn.querySelector("img");
      if (img) img.alt = `${c.name}, ${year} Champion`;
      btn.setAttribute("aria-label", `View ${year} champion stats — ${c.name}`);
    }
  });

  const overlay = document.getElementById("statModal");
  const closeBtn = document.getElementById("modalClose");
  let lastFocused = null;

  function openModal(year) {
    const c = champions[year];
    if (!c) return;
    document.getElementById("modalName").textContent = c.name;
    document.getElementById("modalYear").textContent = year;
    document.getElementById("modalAvg").textContent = c.avg;
    document.getElementById("modalRecord").textContent = c.record;
    if (c.champGame) {
      document.getElementById("modalWinTeam").textContent = c.champGame.winTeam;
      document.getElementById("modalWinScore").textContent = c.champGame.winScore;
      document.getElementById("modalLoseTeam").textContent = c.champGame.loseTeam;
      document.getElementById("modalLoseScore").textContent = c.champGame.loseScore;
    }
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

  document.querySelectorAll(".portrait-frame").forEach((btn) => {
    btn.addEventListener("click", () => openModal(btn.getAttribute("data-year")));
  });
  closeBtn.addEventListener("click", closeModal);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && overlay.classList.contains("active")) closeModal();
  });
}

document.addEventListener("DOMContentLoaded", loadChampions);
