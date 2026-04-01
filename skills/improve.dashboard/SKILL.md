---
name: improve.dashboard
description: Generate an HTML training dashboard from .cogent/ state showing experiments, scores, learnings, TODOs. Pulls live tournament status. Opens in browser. Use for "dashboard", "training status", "show progress".
---

# Improve Dashboard

Generate a self-contained HTML dashboard from `.cogent/` state.

## Steps

1. **Read IMPROVE.md** for game-specific commands (leaderboard, submissions, scoring).

2. **Read improve state**:
   - `.cogent/state.json` — scores, approach stats, sessions
   - `.cogent/todos.md` — TODOs and dead ends

3. **Pull live tournament status**:
   - Run the leaderboard/submissions commands from IMPROVE.md
   - Get current rank, score, matches for each season

4. **Scan session logs** (`.cogent/*/plan.md`):
   - Extract: timestamp, approach (PCO/design), what was tried, result, score
   - Build experiment timeline

5. **Generate HTML** at `~/.agent/diagrams/improve-dashboard.html`:
   - **Hero KPIs**: rank, best score, sessions, gap to next
   - **Score chart** (Chart.js): one line per season, versions on x-axis
   - **Version table**: all submitted versions across all seasons with scores, filterable by season
   - **Experiment log**: sessions with change, result badge, approach tag
   - **Approach stats**: PCO vs IntelligentDesign hit rates
   - **Dead ends**: from todos.md
   - **Active TODOs**: current priorities

6. **Open in browser**: `open ~/.agent/diagrams/improve-dashboard.html`

## Design

Catppuccin Mocha palette (dark-first). Chart.js for graphs. Season tabs for filtering. Responsive grid. Light/dark themes.
