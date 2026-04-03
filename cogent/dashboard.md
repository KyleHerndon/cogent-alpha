# CoGames Dashboard

Additional panels for the cogent dashboard, specific to CoGames.

## Data to Collect

1. **Tournament status** — Run leaderboard/match commands from `docs/cogames.md`:
   - Current rank and score per season
   - Recent match results
   - Gap to next rank

2. **Approach stats** — From `cogent/state.json`:
   - PCO vs design attempt counts and improvement rates

3. **Experiment log** — From memory:
   - Each session: timestamp, approach (PCO/design), what changed, result, score delta

## Panels

- **Tournament KPIs**: rank, best score, sessions played, gap to next
- **Score chart**: one line per season, versions on x-axis
- **Version table**: all submitted versions with scores, filterable by season
- **Experiment log**: sessions with change description, result badge, approach tag
- **Approach stats**: PCO vs design hit rates
