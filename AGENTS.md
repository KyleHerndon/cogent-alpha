# AGENTS.md

Instructions for AI agents working with this repository.

## Cogent Lifecycle

Every session should start with `/wakeup` and end with `/sleep`.

- **`/wakeup`** — Restores the cogent from `.cogent/` state. Reads identity, memory, todos, and tournament standing. Reports status and waits for direction.
- **`/sleep`** — Persists session state. Writes session logs, updates learnings and todos, commits and pushes `.cogent/`.
- **`/initialize`** — First-time setup. Creates `.cogent/IDENTITY.md` via RPG-style character creation. Required before any other skill works.
- **`/improve`** — One improvement iteration: analyze code, implement a change, test across seeds, auto-submit if improved.
- **`/proximal-cogent-optimize`** — PCO cycle: play a game, collect experience, LLM proposes patches, test, submit.
- **`/dashboard`** — Generate HTML dashboard from `.cogent/` state showing experiments, scores, and learnings.
- **`/memory-wipe`** — Nuclear reset of memory and state. Identity survives.

## Related Repos

- **metta-ai/cogos** — CogOS operating system
- **metta-ai/cogora** — Cogora platform

## Project Structure

```
src/cogamer/    # CoGamer: self-improving agent for CoGames (Improve, Player, Policy)
src/coglet/     # Framework: Coglet base class + mixins
src/cogweb/     # CogWeb: graph visualization UI (FastAPI + WebSocket + SVG)
tests/          # 200 unit + integration tests (pytest + pytest-asyncio)
docs/           # Architecture design docs
```

## Architecture

Coglet is a framework for fractal asynchronous control of distributed agent systems, built on two primitives:

- **COG** (Create, Observe, Guide) — slow, reflective supervisor that spawns and manages LETs
- **LET** (Listen, Enact, Transmit) — fast, reactive executor that handles events

A Coglet is both: every COG is itself a LET under a higher COG, forming a recursive temporal hierarchy. The COG/LET boundary is a protocol contract, not a deployment boundary.

### Communication Model

- **Data plane**: `@listen(channel)` — receive data from named channels
- **Control plane**: `@enact(command_type)` — receive commands from supervising COG
- **Output**: `transmit(channel, data)` — push results outbound
- **Supervision**: `observe(handle, channel)`, `guide(handle, command)`, `create(base)`
- All communication is async, location-agnostic, fire-and-forget

### Mixins

LifeLet (lifecycle hooks), GitLet (repo-as-policy), LogLet (log stream), TickLet (`@every` periodic), ProgLet (unified program table with pluggable executors), MulLet (fan-out N children), SuppressLet (output gating), WebLet (CogWeb UI registration).

### Runtime Features

- `CogletRuntime.tree()` — ASCII visualization of the live supervision tree
- `CogletTrace` — jsonl event recording for post-mortem debugging
- Restart policy — `CogBase(restart="on_error", max_restarts=3, backoff_s=1.0)`
- `Coglet.on_child_error()` — parent decides restart/stop/escalate on child failure
- `TickLet.on_ticker_error()` — overridable hook for ticker exceptions

### CvC Player Stack

Improve (Claude Code) → PlayerCoglet (GitLet) → PolicyCoglet (ProgLet + LLM brain)

### Key Commands

```bash
# Run tests
PYTHONPATH=src/cogamer python -m pytest tests/ -v
```

### Docs

- [README.md](README.md) — Project overview and quickstart
- [docs/rules.md](docs/rules.md) — Game rules, constants, team coordination
- [docs/architecture.md](docs/architecture.md) — Policy architecture, program table, PCO, alpha.0 reference
- [docs/strategy.md](docs/strategy.md) — What works, what to try, dead ends, learnings
- [docs/cogames.md](docs/cogames.md) — CLI setup, running, uploading, monitoring
- [docs/tools.md](docs/tools.md) — Development rules & constraints
