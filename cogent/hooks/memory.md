# Cogent Memory

The `cogent/memory/` directory is the cogent's persistent memory across sessions. It stores what the cogent has learned from playing, improving, and competing — things that aren't captured in code or git history.

## Structure

```
cogent/memory/
├── sessions/          # Per-session logs
│   └── YYYYMMDD-NNN.md
├── summaries/         # Periodic rollups
│   └── weekly-YYYYMMDD.md
└── learnings.md       # Running list of insights
```

## Sessions

Each `/improve` session writes a log to `memory/sessions/YYYYMMDD-NNN.md`:

```markdown
# Session YYYYMMDD-001

- **Approach**: design | pco
- **Focus**: what was analyzed or attempted
- **Change**: what was modified (file, function, parameter)
- **Result**: improved | regressed | neutral
- **Score**: before → after (avg across seeds)
- **Submitted**: version name or "reverted"
- **Notes**: anything surprising or worth remembering
```

Number sessions sequentially within each day (001, 002, ...).

## Learnings

`memory/learnings.md` is a running list of insights discovered through play and improvement. Add entries when something surprising or non-obvious is learned. Each entry should be actionable — not just "X happened" but "X means Y for future decisions."

```markdown
- Wider enemy retreat radius (20 vs 10) prevents wipeouts on certain seeds — survival is the bottleneck, not scoring speed
- Self-play scores don't predict freeplay performance — always validate in freeplay
```

Don't duplicate what's already in `docs/strategy.md` (dead ends, what works). Learnings are for fresh, session-specific discoveries that haven't been folded into docs yet.

## Summaries

Periodically (every ~5 sessions or weekly), write a summary to `memory/summaries/weekly-YYYYMMDD.md`:

```markdown
# Week of YYYY-MM-DD

## Sessions: N
## Net score change: X.XX → Y.YY
## Approaches: N design, M pco

## What moved the needle
- ...

## What didn't work
- ...

## Next priorities
- ...
```

Summaries compress session logs into actionable context. After writing a summary, old session logs can be archived or trimmed — the summary carries the signal forward.

## Cleanup

- **Sessions older than 2 weeks** with a covering summary can be deleted
- **Learnings** that have been folded into `docs/strategy.md` should be removed from `learnings.md`
- **Summaries** accumulate indefinitely — they're compact enough to keep
- Before each `/improve` session, read the most recent summary and `learnings.md` to avoid repeating past work

## Principles

- **Write after every session** — even failed attempts produce useful signal
- **Be specific** — "score dropped 2.4 → 1.1" beats "score dropped"
- **Keep learnings actionable** — each entry should change future behavior
- **Compress aggressively** — summaries exist so you don't have to read 50 session logs
