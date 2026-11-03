// Special trading cards: end-of-season awards and the postseason
// collection. These are finished artwork (front and back), not built from
// stats.json, so each one is listed here by hand once its images exist.
//
// Images live in images/cards/awards/:
//   <file>-front.jpg and <file>-back.jpg
// A missing front shows a plain stand-in with the award and manager name.
//
// Sections are shown in CARD_SECTIONS order for each season, after that
// season's regular-season cards. Within Special Inserts, awards
// follow AWARD_ORDER. To add a new kind of card, add its section or award
// here.

const CARD_SECTIONS = [
  { id: "regular", title: "Regular Season" },
  { id: "recognition", title: "Special Inserts" },
  { id: "postseason", title: "Post Season Collection" },
];

const AWARD_ORDER = ["Points Champion", "Division Champion", "Last Place"];

const SPECIAL_CARDS = [
  { year: 2023, section: "recognition", award: "Points Champion", manager: "Greg Wigton",
    file: "points-champion-2023-greg-wigton" },
  { year: 2024, section: "recognition", award: "Points Champion", manager: "Carl Bruce",
    file: "points-champion-2024-carl-bruce" },
  { year: 2025, section: "recognition", award: "Points Champion", manager: "Greg Wigton",
    file: "points-champion-2025-greg-wigton" },
  { year: 2025, section: "recognition", award: "Last Place", manager: "Daniel Bahamonde",
    file: "last-place-2025-daniel-bahamonde" },
  // Parallel of the 2025 Last Place card, issued in the 2026 set.
  { year: 2026, section: "recognition", award: "Punishment Insert", manager: "Daniel Bahamonde",
    file: "punishment-2026-daniel-bahamonde" },
];
