# On Wake

Cogamer-specific wake hook. Runs after the platform has already loaded identity, memory, and todos.

## Steps

1. **Install dependencies** — Run `uv sync` to install the project and cogames CLI.

2. **Verify cogames CLI** — Run `cogames --version` to confirm it's installed. If it fails, run `uv pip install cogames`.

3. **Verify auth** — Run `cogames auth status`. If not authenticated, run `cogames auth set-token <token>` using the token from secrets.

4. **Read approach state** — Read `cogent/state.json` to understand PCO vs design attempt history.

5. **Check tournament standing** — Run leaderboard commands from `docs/cogames.md` to see current rank and recent matches.

6. **Report status** — Brief summary:
   - Current scores / ranking
   - Top priorities from todos
   - Recommended next action

7. **Start improvement loop** — Run `/loop 30m improve.md` to continuously improve the policy.
