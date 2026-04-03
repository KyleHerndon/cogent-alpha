# On Sleep

Cogamer-specific sleep hook. Runs before the platform commits, pushes, and shuts down.

## Steps

1. **Update approach state** — Write current `approach_stats` to `cogent/state.json`.

2. **Fold stale learnings** — If any entries in `cogent/memory/learnings.md` have already been incorporated into `docs/strategy.md`, remove them.
