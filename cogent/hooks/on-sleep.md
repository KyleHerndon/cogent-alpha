# On Sleep

Cogamer-specific sleep hook. Runs before the platform commits, pushes, and shuts down.

## Steps

1. **Update approach state** — Write current `approach_stats` to `cogent/state.json`.

2. **Fold stale learnings** — If any learnings have already been incorporated into docs, remove them from memory.
