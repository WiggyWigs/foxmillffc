# In progress

Work in TestSite/ that has not been promoted to live yet. Stays in
TestSite/ only: never promoted, not wiped by "Refresh TestSite from live",
and not listed by "Show TestSite changes".

Feature: Trading Cards page (trading-cards.html)
Status: NOT READY        <!-- READY or NOT READY -->

Waiting on: cards for Brian Kleinhenz and Eddie McCumiskey (template.jpg
stands in), badge art for Monday Night Miracle / Monday Night Master / Lineup King, and a
"TEST weekly update" run to recompute stats.json's player_cards.
Scripts change: never promote on Monday night or Tuesday morning.

Files (paths relative to TestSite/, paste into "Promote TestSite to live"):
- trading-cards.html
- trading-cards.js
- styles.css
- nav.html
- scripts/player_cards.py
- scripts/espn_pull.py
- scripts/ingest_csv.py
- images/cards/template.jpg
- images/cards/back-2026.jpg (card back; next season needs back-2027.jpg)
- images/cards/back-01-2026.jpg ... back-12-2026.jpg (per-rank backs, when made)
- images/cards/<each manager>-2026.jpg
- images/badges/<each badge>.png
- images/badges/rank-01.png ... rank-12.png
