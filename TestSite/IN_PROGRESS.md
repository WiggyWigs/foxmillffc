# In progress

Work in TestSite/ that has not been promoted to live yet. Stays in
TestSite/ only: never promoted, not wiped by "Refresh TestSite from live",
and not listed by "Show TestSite changes".

Feature: Player Cards page
Status: NOT READY        <!-- READY or NOT READY -->

Waiting on: the real card, badge and rank-stamp artwork, and a
"TEST weekly update" run to fill stats.json's player_cards.
Scripts change: promote after a Tuesday live run, never Mon night/Tue morning.
images/cards/card-placeholder.jpg is the stand-in for missing cards: promote it.

Files (paths relative to TestSite/, paste into "Promote TestSite to live"):
- player-cards.html
- player-cards.js
- styles.css
- nav.html
- scripts/player_cards.py
- scripts/espn_pull.py
- scripts/ingest_csv.py
- images/cards/card-placeholder.jpg
- images/cards/<each manager>-2026.jpg
- images/badges/<each badge>.png
- images/badges/rank-01.png ... rank-12.png
