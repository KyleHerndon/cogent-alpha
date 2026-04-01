# helpers — Pure utility functions

Stateless helper functions used by the CvC engine mixins. No side effects, no agent state.

| File | Purpose |
|---|---|
| `types.py` | KnownEntity dataclass, type definitions |
| `geometry.py` | Manhattan distance, direction calculation, move deltas, greedy step |
| `resources.py` | Inventory helpers, deposit thresholds, heart batching, role gear checks |
| `targeting.py` | Aligner/scrambler target scoring, alignment network checks, explore offsets |
