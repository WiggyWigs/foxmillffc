// Trading card badges, shared by the Trading Cards page and the Current
// Season page's "Week N Badges" section: names, image files, pop-up
// rules, the one-line detail for each earned badge, and which badges a
// given week added. Badge data itself comes from stats.json's
// "player_cards" (scripts/player_cards.py).
//
// Load this before the page script. Its functions use the page's own
// escapeHtml() and ordinal(), which are defined by the time they run.

const BADGES = {
  longest_win_streak: {
    name: "Longest Win Streak", file: "longest-win-streak.png", numbered: true,
    // Orange banner, no cream centre: light number, a little higher up.
    numberStyle: "light", numberTop: "44%",
    rule: "This manager's longest run of straight wins this season.",
  },
  weekly_high_score: {
    name: "Weekly High Score", file: "weekly-high-score.png", numbered: true,
    rule: "Weeks with the league's highest score.",
  },
  superstar: {
    name: "Superstar", file: "superstar.png", numbered: true,
    // Trophy: the number goes in the cup, not the middle of the image.
    numberTop: "30%",
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
    name: "Ice Cold", file: "ice-cold.png", numbered: true,
    numberTop: "50%",
    rule: "Lost 5 or more games in a row. The number is the longest losing streak.",
  },
  monday_night_miracle: {
    name: "Monday Night Miracle", file: "monday-night-miracle.png", numbered: false,
    initials: "MIR",
    rule: "Led going into Monday night with fewer players left, and held on to win.",
  },
  monday_night_master: {
    name: "Monday Night Master", file: "monday-night-master.png", numbered: false,
    initials: "MAS",
    rule: "Trailed going into Monday night and came back to win.",
  },
  lineup_king: {
    name: "Lineup King", file: "lineup-king.png", numbered: false,
    rule: "Started the best lineup the roster allowed: nobody on the bench could have helped.",
  },
  businessman: {
    name: "Businessman", file: "businessman.png", numbered: false,
    rule: "Most transactions (adds, drops and trades) in the regular season.",
  },
};

function badgeEventLines(badge) {
  const ev = badge.events || [];
  const score = (e) => `${e.manager_score.toFixed(2)}–${e.opponent_score.toFixed(2)}`;
  const opp = (e) => escapeHtml(e.opponent);
  switch (badge.id) {
    case "longest_win_streak": {
      const first = ev[0]?.week, last = ev[ev.length - 1]?.week;
      return [`${ev.length} straight wins, Weeks ${first}–${last}`]
        .concat(ev.map((e) => `Week ${e.week}: beat ${opp(e)} ${score(e)}`));
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
    case "lineup_king":
      return ev.map((e) => `Week ${e.week}: ${e.points.toFixed(2)} points`);
    case "monday_night_miracle":
    case "monday_night_master":
      // "Week 1: Led by 14.66 points going into Monday with a two-player
      // disadvantage, beat Kevin Mallon 79.16–78.84"
      return ev.map((e) => {
        const gap = e.manager_before_monday - e.opponent_before_monday;
        const side = gap >= 0 ? `Led by ${gap.toFixed(2)}` : `Trailed by ${(-gap).toFixed(2)}`;
        return `Week ${e.week}: ${side} points going into Monday `
          + `${playerEdge(e.manager_monday_players - e.opponent_monday_players)}, beat ${opp(e)} ${score(e)}`;
      });
    default:
      return [];
  }
}

// Players-left difference going into Monday, from the badge winner's side.
function playerEdge(diff) {
  if (diff === 0) return "with the same number of players left";
  const words = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];
  const n = Math.abs(diff);
  return `with a ${words[n] || n}-player ${diff > 0 ? "advantage" : "disadvantage"}`;
}

// Badges added or increased in `week`, for "Week N Badges":
//   [{ manager, badge, isNew, change, line }]
// isNew: first time on the card. Otherwise `change` says what went up
// ("now 3", "×2"). `line` is the same one-line detail as the card pop-up,
// for that week only. Sorted by manager (standings order), then badge.
function weekBadgeHighlights(season, week) {
  const out = [];
  for (const card of season.cards) {
    for (const badge of card.badges) {
      const ev = badge.events || [];
      let hit;
      if (badge.id === "longest_win_streak") {
        // The longest streak grew this week (its last game was this week).
        hit = ev.length && ev[ev.length - 1].week === week;
      } else if (badge.id === "ice_cold") {
        hit = ev.some((e) => e.end_week === week);
      } else {
        hit = ev.some((e) => e.week === week);
      }
      if (!hit) continue;

      const isNew = badge.earned_week === week;
      let change = "";
      let lineEvents = ev.filter((e) => e.week === week);
      if (badge.id === "longest_win_streak") {
        change = `now ${badge.count}`;
        lineEvents = ev;
      } else if (badge.id === "ice_cold") {
        lineEvents = ev.filter((e) => e.end_week === week);
        change = `now ${lineEvents[0].length}`;
      } else if (badge.count != null) {
        change = `×${badge.count}`;
      } else {
        change = `×${ev.length}`;
      }
      const lines = badgeEventLines({ ...badge, events: lineEvents });
      out.push({ manager: card.manager, badge, isNew, change, line: lines[0] || "" });
    }
  }
  return out;
}
