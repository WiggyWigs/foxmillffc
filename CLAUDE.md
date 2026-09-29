# Foxmill FFC site — working rules

## Structure

- `NewSite/` is the **live** site.
- `TestSite/` is its **test twin**: the same file names and the same code (pages, JS, CSS, images, fonts, `scripts/`). The only folder that differs is `data/`.
- This works because pages load data with relative paths (`fetch("data/stats.json")`) and every Python script finds its data at `SCRIPT_DIR.parent / "data"`. Code in `TestSite/` automatically reads and writes `TestSite/data/`. Never hardcode `NewSite` or `TestSite` in a page or script, and never add `-test` / `_test` variants of files.
- `nav.js` shows the "TEST ENVIRONMENT" banner whenever the URL path contains `/TestSite/`. Nothing else in the code knows which copy it is running in.

## Where changes go

- **All development happens in `TestSite/`.** Change a page, script or style there, and test it there.
- **Promote to live with the "Promote TestSite to live" workflow.** It copies whole files from `TestSite/` into `NewSite/`, never `data/`. Never edit files under `NewSite/` by hand, and never paste code into them. Hand-copied code has broken the live site before.
- If the "Promote TestSite to live" workflow is missing from `.github/workflows/`, stop and ask. Do not promote by editing `NewSite/` directly.
- To bring `TestSite/` back in line with live, run "Refresh TestSite from live". It overwrites everything in `TestSite/` except `data/`, so any unpromoted work in `TestSite/` is lost.

## Data

- **Never edit anything under `*/data/` by hand** (`NewSite/data/` or `TestSite/data/`). Only the workflows write data:
  - "Weekly stats update" writes `NewSite/data/`.
  - "TEST weekly update (historical cutoff)" writes `TestSite/data/`.
- Also treat the generated state files in `scripts/` (`team_mapping.json`, `manager_lore.json`, `lore_rotation_state.json`, `lore_sync_state.json`) as workflow-owned. Their contents change through the workflows, not by hand.

## Weekly schedule

- The live update ("Weekly stats update") runs on **Tuesdays**. It is triggered manually from the Actions tab; there is no cron schedule.
- **Do not promote script changes (`scripts/*.py` or the files they read) on Monday night or Tuesday morning.** A half-tested script change landing right before the live run can break that week's stats and recaps. Promote scripts after Tuesday's run, and test them first with "TEST weekly update".

## Git

- Every change goes on a branch and is merged through a pull request. **Never push to `main`.**
- The workflows' own automated commits to `main` (stats, lore, test data) are the only exception.
