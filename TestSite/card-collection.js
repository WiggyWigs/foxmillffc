// Special trading cards: end-of-season awards and the postseason
// collection. These are finished artwork (front and back), not built from
// stats.json, so each one is listed here by hand once its images exist.
//
// Images live in images/cards/awards/:
//   <file>-front.jpg and <file>-back.jpg
// A missing front shows a plain stand-in with the award and manager name.
//
// Sections are shown in CARD_SECTIONS order for each season, after that
// season's regular-season cards. Within End of Season Recognition, awards
// follow AWARD_ORDER. To add a new kind of card, add its section or award
// here.

const CARD_SECTIONS = [
  { id: "regular", title: "Regular Season" },
  { id: "recognition", title: "End of Season Recognition" },
  { id: "postseason", title: "Post Season Collection" },
];

const AWARD_ORDER = ["Points Champion", "Division Champion", "Loser"];

const SPECIAL_CARDS = [
  { year: 2023, section: "recognition", award: "Points Champion", manager: "Greg Wigton",
    file: "points-champion-2023-greg-wigton" },
  { year: 2024, section: "recognition", award: "Points Champion", manager: "Carl Bruce",
    file: "points-champion-2024-carl-bruce" },
  { year: 2025, section: "recognition", award: "Points Champion", manager: "Greg Wigton",
    file: "points-champion-2025-greg-wigton" },
];
