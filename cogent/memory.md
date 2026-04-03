# Cogamer Memory

Extends the base cogent memory system with game-specific guidance.

## What to Remember

- **Score deltas** — Before/after averages (across 5+ seeds) when a change moves the needle. Include which seeds and whether LLM was enabled.
- **Dead ends** — Approaches that regressed or had no effect, with enough detail to avoid repeating them.
- **Tournament vs local gaps** — Differences between local self-play scores and tournament results. These often reveal assumptions that don't hold against real opponents.
- **Opponent patterns** — Observed strategies from tournament opponents (e.g. alpha.0's hotspot tracking, retreat margins).
- **Resource bottlenecks** — Which element bottlenecked and under what map/seed conditions.

## What NOT to Remember

- Raw scores from a single seed (noise).
- Code changes — the git log has these.
- Anything already in `docs/cvc.md` or `docs/architecture.md`.

## Approach State

`cogent/state.json` tracks PCO vs design attempt counts and improvement rates. Update this at end of session (on-sleep hook handles it).
